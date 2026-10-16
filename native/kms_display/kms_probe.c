#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

/* 48-byte FlipEvent records: 24 MiB, enough for ~146 min at 59.82 Hz. */
#define STREAM_EVENT_CAPACITY 524288U

#include <drm.h>
#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#include "drm_lease.h"
#include "frame_semantics.h"

#define MAX_FRAMES 10000U
#define POLL_TIMEOUT_MS 2000
#define STREAM_MAGIC "RPIKMS1\0"
#define STREAM_MAGIC_BYTES 8U
#define STREAM_VERSION 1U
#define STREAM_FRAME_HEADER_BYTES 32U
#define DIAGNOSTIC_SAMPLE_CAPACITY 4096U

static volatile sig_atomic_t stop_requested;

typedef struct {
    const char *device;
    const char *connector;
    unsigned int width;
    unsigned int height;
    double refresh;
    double tolerance;
    uint32_t format;
    const char *format_name;
    unsigned int frames;
    unsigned int patch_size;
    unsigned int patch_on;
    unsigned int patch_off;
    const char *patch_corner;
    bool json;
    bool probe_only;
    bool lease;
    bool lease_discover;
    bool stream;
    bool color_set;
    unsigned int color[3];
    const char *frame_file;
} Options;

typedef struct {
    uint64_t count;
    double sum;
    double minimum;
    double maximum;
    double mean;
    double m2;
    unsigned int outside_tolerance;
    unsigned int long_intervals;
    unsigned int short_intervals;
    unsigned int estimated_dropped;
    double samples[DIAGNOSTIC_SAMPLE_CAPACITY];
    size_t sample_count;
} IntervalStats;

typedef struct {
    unsigned int frame_index;
    unsigned int buffer_index;
    bool photodiode_on;
    uint64_t kernel_event_ns;
    uint64_t callback_monotonic_ns;
    uint64_t callback_realtime_ns;
    uint32_t kernel_sequence;
} FlipEvent;

typedef struct {
    uint32_t handle;
    uint32_t framebuffer;
    uint32_t pitch;
    uint64_t size;
    void *map;
} DumbBuffer;

typedef struct {
    int fd;
    char device[PATH_MAX];
    bool device_exists;
    bool device_readable;
    drmModeRes *resources;
    bool resources_enumerated;
    drmModeConnector *connector;
    bool connector_resolved;
    drmModeCrtc *original_crtc;
    drmModePlaneRes *planes;
    uint32_t crtc_id;
    bool mode_compatible;
    bool crtc_resolved;
    uint32_t primary_plane_id;
    uint32_t primary_format_count;
    uint32_t primary_formats[64];
    bool primary_plane_compatible;
    bool timestamp_capability_known;
    bool timestamp_monotonic;
    drmModeModeInfo mode;
    bool mode_selected;
    bool lease_active;
    uint32_t *lease_objects;
    int lease_object_count;
    bool modeset_active;
} KmsState;

typedef struct {
    FlipEvent *events;
    unsigned int event_capacity;
    uint64_t completed;
    unsigned int missed;
    bool pending;
    KmsFrameMetadata pending_frame;
    bool all_kernel_timestamps;
    bool frame_indices_contiguous;
    bool kernel_sequences_contiguous;
    bool photodiode_metadata_valid;
    bool have_previous_frame;
    bool have_previous_kernel_sequence;
    unsigned int previous_frame_index;
    uint32_t previous_kernel_sequence;
    uint64_t previous_kernel_event_ns;
    uint64_t previous_callback_monotonic_ns;
    uint64_t first_kernel_event_ns;
    uint64_t last_kernel_event_ns;
    uint64_t first_callback_monotonic_ns;
    uint64_t last_callback_monotonic_ns;
    uint64_t first_callback_realtime_ns;
    uint64_t last_callback_realtime_ns;
    IntervalStats kernel_intervals;
    IntervalStats callback_intervals;
    double expected_interval_us;
} FlipState;

typedef struct {
    uint64_t frame_index;
    uint64_t producer_sequence;
    bool photodiode_on;
} StreamFrameMetadata;

static void signal_handler(int signal_number) {
    (void)signal_number;
    stop_requested = 1;
}

static uint64_t clock_ns(clockid_t clock_id) {
    struct timespec value;
    if (clock_gettime(clock_id, &value) != 0) {
        return 0;
    }
    return (uint64_t)value.tv_sec * 1000000000ULL + (uint64_t)value.tv_nsec;
}

static void install_signal_handlers(void) {
    struct sigaction action = {0};
    action.sa_handler = signal_handler;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
}

static const char *connector_type_name(uint32_t type) {
    switch (type) {
    case DRM_MODE_CONNECTOR_HDMIA:
        return "HDMI-A";
    case DRM_MODE_CONNECTOR_HDMIB:
        return "HDMI-B";
    case DRM_MODE_CONNECTOR_DVID:
        return "DVI-D";
    case DRM_MODE_CONNECTOR_DVII:
        return "DVI-I";
    case DRM_MODE_CONNECTOR_DisplayPort:
        return "DP";
    case DRM_MODE_CONNECTOR_eDP:
        return "eDP";
    default:
        return "UNKNOWN";
    }
}

static void connector_name(const drmModeConnector *connector, char *buffer, size_t size) {
    snprintf(
        buffer,
        size,
        "%s-%u",
        connector_type_name(connector->connector_type),
        connector->connector_type_id
    );
}

static bool same_connector(const drmModeConnector *connector, const char *wanted) {
    char name[32];
    connector_name(connector, name, sizeof(name));
    return strcmp(name, wanted) == 0;
}

static uint32_t format_from_name(const char *name) {
    if (strcmp(name, "RGB565") == 0) {
        return DRM_FORMAT_RGB565;
    }
    if (strcmp(name, "XRGB8888") == 0) {
        return DRM_FORMAT_XRGB8888;
    }
    return 0;
}

static unsigned int format_bpp(uint32_t format) {
    return format == DRM_FORMAT_RGB565 ? 16U : 32U;
}

static double mode_refresh(const drmModeModeInfo *mode) {
    if (mode->htotal == 0 || mode->vtotal == 0) {
        return (double)mode->vrefresh;
    }
    double refresh = (double)mode->clock * 1000.0 /
                     ((double)mode->htotal * (double)mode->vtotal);
    if (mode->flags & DRM_MODE_FLAG_INTERLACE) {
        refresh *= 2.0;
    }
    if (mode->flags & DRM_MODE_FLAG_DBLSCAN) {
        refresh *= 0.5;
    }
    return refresh;
}

static bool format_supported(const drmModePlane *plane, uint32_t format) {
    for (uint32_t index = 0; index < plane->count_formats; ++index) {
        if (plane->formats[index] == format) {
            return true;
        }
    }
    return false;
}

static int plane_type(int fd, uint32_t plane_id) {
    drmModeObjectProperties *properties = drmModeObjectGetProperties(
        fd, plane_id, DRM_MODE_OBJECT_PLANE
    );
    if (properties == NULL) {
        return -1;
    }
    int result = -1;
    for (uint32_t index = 0; index < properties->count_props; ++index) {
        drmModePropertyRes *property = drmModeGetProperty(fd, properties->props[index]);
        if (property == NULL) {
            continue;
        }
        if (strcmp(property->name, "type") == 0) {
            result = (int)properties->prop_values[index];
            drmModeFreeProperty(property);
            break;
        }
        drmModeFreeProperty(property);
    }
    drmModeFreeObjectProperties(properties);
    return result;
}

static int find_crtc_for_connector(
    int fd, const drmModeRes *resources, const drmModeConnector *connector, uint32_t *crtc_id
) {
    for (int encoder_index = 0; encoder_index < connector->count_encoders; ++encoder_index) {
        drmModeEncoder *encoder = drmModeGetEncoder(fd, connector->encoders[encoder_index]);
        if (encoder == NULL) {
            continue;
        }
        for (int crtc_index = 0; crtc_index < resources->count_crtcs; ++crtc_index) {
            if (encoder->possible_crtcs & (1U << crtc_index)) {
                *crtc_id = resources->crtcs[crtc_index];
                drmModeFreeEncoder(encoder);
                return 0;
            }
        }
        drmModeFreeEncoder(encoder);
    }
    return -1;
}

static int select_mode(const Options *options, KmsState *state) {
    double best_difference = HUGE_VAL;
    int best_index = -1;
    for (int index = 0; index < state->connector->count_modes; ++index) {
        drmModeModeInfo *mode = &state->connector->modes[index];
        if ((unsigned int)mode->hdisplay != options->width ||
            (unsigned int)mode->vdisplay != options->height) {
            continue;
        }
        double difference = fabs(mode_refresh(mode) - options->refresh);
        if (difference < best_difference) {
            best_difference = difference;
            best_index = index;
        }
    }
    if (best_index < 0) {
        fprintf(stderr, "requested mode %ux%u is unavailable on %s\n",
                options->width, options->height, options->connector);
        return -1;
    }
    if (best_difference > options->tolerance) {
        fprintf(stderr, "requested refresh %.6gHz is unavailable on %s; nearest %.6gHz\n",
                options->refresh, options->connector,
                mode_refresh(&state->connector->modes[best_index]));
        return -1;
    }
    state->mode = state->connector->modes[best_index];
    state->mode_selected = true;
    return 0;
}

static int inspect_state_fd(const Options *options, KmsState *state, int fd, const char *device) {
    state->fd = fd;
    snprintf(state->device, sizeof(state->device), "%s", device);
    state->device_exists = true;
    state->device_readable = true;
    uint64_t timestamp_capability = 0;
    if (drmGetCap(state->fd, DRM_CAP_TIMESTAMP_MONOTONIC, &timestamp_capability) == 0) {
        state->timestamp_capability_known = true;
        state->timestamp_monotonic = timestamp_capability != 0;
    }
    state->resources = drmModeGetResources(state->fd);
    if (state->resources == NULL) {
        fprintf(stderr, "cannot enumerate DRM resources on %s: %s\n",
                device, strerror(errno));
        return -1;
    }
    state->resources_enumerated = true;
    if (drmSetClientCap(state->fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) != 0) {
        fprintf(stderr, "cannot enable universal DRM planes: %s\n", strerror(errno));
        return -1;
    }
    uint64_t capability = 0;
    if (drmGetCap(state->fd, DRM_CAP_DUMB_BUFFER, &capability) != 0 || capability == 0) {
        fprintf(stderr, "DRM dumb buffers are unavailable\n");
        return -1;
    }
    for (int index = 0; index < state->resources->count_connectors; ++index) {
        drmModeConnector *connector = drmModeGetConnector(
            state->fd, state->resources->connectors[index]
        );
        if (connector == NULL) {
            continue;
        }
        if (same_connector(connector, options->connector)) {
            state->connector = connector;
            state->connector_resolved = true;
            break;
        }
        drmModeFreeConnector(connector);
    }
    if (state->connector == NULL) {
        fprintf(stderr, "configured connector is missing on %s: %s\n", device, options->connector);
        return -1;
    }
    if (state->connector->connection != DRM_MODE_CONNECTED) {
        fprintf(stderr, "configured connector is not connected: %s\n", options->connector);
        return -1;
    }
    if (select_mode(options, state) != 0) {
        return -1;
    }
    state->mode_compatible = true;
    if (find_crtc_for_connector(state->fd, state->resources, state->connector, &state->crtc_id) != 0) {
        fprintf(stderr, "no usable CRTC for configured connector: %s\n", options->connector);
        return -1;
    }
    state->crtc_resolved = true;
    state->original_crtc = drmModeGetCrtc(state->fd, state->crtc_id);
    if (state->original_crtc == NULL) {
        fprintf(stderr, "cannot read original CRTC state %u: %s\n",
                state->crtc_id, strerror(errno));
        return -1;
    }
    state->planes = drmModeGetPlaneResources(state->fd);
    if (state->planes == NULL) {
        fprintf(stderr, "cannot enumerate DRM planes: %s\n", strerror(errno));
        return -1;
    }
    bool usable_primary = false;
    for (uint32_t index = 0; index < state->planes->count_planes; ++index) {
        drmModePlane *plane = drmModeGetPlane(state->fd, state->planes->planes[index]);
        if (plane == NULL) {
            continue;
        }
        bool usable = false;
        for (int crtc_index = 0; crtc_index < state->resources->count_crtcs; ++crtc_index) {
            if (state->resources->crtcs[crtc_index] == state->crtc_id &&
                (plane->possible_crtcs & (1U << crtc_index))) {
                usable = true;
                break;
            }
        }
        int type = plane_type(state->fd, plane->plane_id);
        if (usable && type == DRM_PLANE_TYPE_PRIMARY &&
            format_supported(plane, options->format)) {
            state->primary_plane_id = plane->plane_id;
            state->primary_format_count = plane->count_formats > 64 ? 64 : plane->count_formats;
            memcpy(state->primary_formats, plane->formats,
                   state->primary_format_count * sizeof(state->primary_formats[0]));
            usable_primary = true;
        }
        drmModeFreePlane(plane);
    }
    if (!usable_primary) {
        fprintf(stderr, "no usable primary plane supports %s on CRTC %u\n",
                options->format_name, state->crtc_id);
        return -1;
    }
    state->primary_plane_compatible = true;
    return 0;
}

static int discover_state(const Options *options, KmsState *state, const char *device) {
    state->device_exists = access(device, F_OK) == 0;
    state->device_readable = access(device, R_OK) == 0;
    state->fd = open(device, O_RDWR | O_CLOEXEC);
    if (state->fd < 0) {
        fprintf(stderr, "cannot open DRM device %s (exists=%s readable=%s): %s\n",
                device, state->device_exists ? "true" : "false",
                state->device_readable ? "true" : "false", strerror(errno));
        return -1;
    }
    return inspect_state_fd(options, state, state->fd, device);
}

static int discover_device(const Options *options, KmsState *state) {
    if (options->device != NULL) {
        return discover_state(options, state, options->device);
    }
    for (unsigned int index = 0; index < 16; ++index) {
        char device[PATH_MAX];
        snprintf(device, sizeof(device), "/dev/dri/card%u", index);
        if (discover_state(options, state, device) == 0) {
            return 0;
        }
        if (state->fd >= 0) {
            if (state->planes != NULL) {
                drmModeFreePlaneResources(state->planes);
                state->planes = NULL;
            }
            if (state->original_crtc != NULL) {
                drmModeFreeCrtc(state->original_crtc);
                state->original_crtc = NULL;
            }
            if (state->connector != NULL) {
                drmModeFreeConnector(state->connector);
                state->connector = NULL;
            }
            if (state->resources != NULL) {
                drmModeFreeResources(state->resources);
                state->resources = NULL;
            }
            close(state->fd);
            state->fd = -1;
        }
    }
    fprintf(stderr, "no DRM card exposes connected connector %s\n", options->connector);
    return -1;
}

static bool lease_contains(const KmsState *state, uint32_t object_id) {
    for (int index = 0; index < state->lease_object_count; ++index) {
        if (state->lease_objects[index] == object_id) {
            return true;
        }
    }
    return false;
}

static int validate_lease_objects(KmsState *state) {
    drmModeObjectListPtr lease = drmModeGetLease(state->fd);
    if (lease == NULL || lease->count == 0) {
        fprintf(stderr, "leased DRM fd returned no lease object set: %s\n", strerror(errno));
        free(lease);
        return -1;
    }
    state->lease_object_count = (int)lease->count;
    state->lease_objects = calloc(lease->count, sizeof(*state->lease_objects));
    if (state->lease_objects == NULL) {
        fprintf(stderr, "cannot allocate leased DRM object list\n");
        free(lease);
        state->lease_object_count = 0;
        return -1;
    }
    memcpy(state->lease_objects, lease->objects,
           lease->count * sizeof(*state->lease_objects));
    free(lease);
    if (!lease_contains(state, state->connector->connector_id) ||
        !lease_contains(state, state->crtc_id) ||
        !lease_contains(state, state->primary_plane_id)) {
        fprintf(stderr,
                "leased DRM object set is missing connector %u, CRTC %u, or primary plane %u\n",
                state->connector->connector_id, state->crtc_id, state->primary_plane_id);
        return -1;
    }
    state->lease_active = true;
    return 0;
}

static int create_dumb_buffer(const Options *options, KmsState *state, DumbBuffer *buffer) {
    struct drm_mode_create_dumb create = {0};
    create.width = options->width;
    create.height = options->height;
    create.bpp = format_bpp(options->format);
    if (drmIoctl(state->fd, DRM_IOCTL_MODE_CREATE_DUMB, &create) != 0) {
        fprintf(stderr, "DRM_IOCTL_MODE_CREATE_DUMB failed: %s\n", strerror(errno));
        return -1;
    }
    buffer->handle = create.handle;
    buffer->pitch = create.pitch;
    buffer->size = create.size;
    uint32_t handles[4] = {buffer->handle, 0, 0, 0};
    uint32_t pitches[4] = {buffer->pitch, 0, 0, 0};
    uint32_t offsets[4] = {0, 0, 0, 0};
    if (drmModeAddFB2(state->fd, options->width, options->height, options->format,
                      handles, pitches, offsets, &buffer->framebuffer, 0) != 0) {
        fprintf(stderr, "drmModeAddFB2 failed: %s\n", strerror(errno));
        return -1;
    }
    struct drm_mode_map_dumb map = {0};
    map.handle = buffer->handle;
    if (drmIoctl(state->fd, DRM_IOCTL_MODE_MAP_DUMB, &map) != 0) {
        fprintf(stderr, "DRM_IOCTL_MODE_MAP_DUMB failed: %s\n", strerror(errno));
        return -1;
    }
    buffer->map = mmap(NULL, buffer->size, PROT_READ | PROT_WRITE, MAP_SHARED,
                       state->fd, map.offset);
    if (buffer->map == MAP_FAILED) {
        buffer->map = NULL;
        fprintf(stderr, "mmap dumb buffer failed: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

static void destroy_dumb_buffer(KmsState *state, DumbBuffer *buffer) {
    if (buffer->map != NULL) {
        munmap(buffer->map, buffer->size);
        buffer->map = NULL;
    }
    if (buffer->framebuffer != 0) {
        drmModeRmFB(state->fd, buffer->framebuffer);
        buffer->framebuffer = 0;
    }
    if (buffer->handle != 0) {
        struct drm_mode_destroy_dumb destroy = {.handle = buffer->handle};
        drmIoctl(state->fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy);
        buffer->handle = 0;
    }
}

static uint16_t rgb565(unsigned int red, unsigned int green, unsigned int blue) {
    return (uint16_t)(((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3));
}

static void fill_buffer(const Options *options, DumbBuffer *buffer, unsigned int frame_index) {
    unsigned int background = frame_index % 2U ? 255U : 0U;
    unsigned int patch = frame_index % 2U ? options->patch_off : options->patch_on;
    unsigned int red = options->color_set ? options->color[0] : background;
    unsigned int green = options->color_set ? options->color[1] : background;
    unsigned int blue = options->color_set ? options->color[2] : background;
    unsigned int patch_x = strstr(options->patch_corner, "left") != NULL
                               ? 0 : options->width > options->patch_size
                               ? options->width - options->patch_size : 0;
    unsigned int patch_y = strstr(options->patch_corner, "top") != NULL
                               ? 0 : options->height > options->patch_size
                               ? options->height - options->patch_size : 0;
    if (options->format == DRM_FORMAT_RGB565) {
        uint16_t background_pixel = rgb565(red, green, blue);
        uint16_t patch_pixel = rgb565(patch, patch, patch);
        for (unsigned int y = 0; y < options->height; ++y) {
            uint16_t *row = (uint16_t *)((char *)buffer->map + y * buffer->pitch);
            for (unsigned int x = 0; x < options->width; ++x) {
                row[x] = (x >= patch_x && y >= patch_y) ? patch_pixel : background_pixel;
            }
        }
    } else {
        uint32_t background_pixel = (red << 16) | (green << 8) | blue;
        uint32_t patch_pixel = (patch << 16) | (patch << 8) | patch;
        for (unsigned int y = 0; y < options->height; ++y) {
            uint32_t *row = (uint32_t *)((char *)buffer->map + y * buffer->pitch);
            for (unsigned int x = 0; x < options->width; ++x) {
                row[x] = (x >= patch_x && y >= patch_y) ? patch_pixel : background_pixel;
            }
        }
    }
}

static int load_frame_file(const Options *options, DumbBuffer buffers[2]) {
    FILE *file = fopen(options->frame_file, "rb");
    if (file == NULL) {
        fprintf(stderr, "cannot open frame file %s: %s\n",
                options->frame_file, strerror(errno));
        return -1;
    }
    size_t row_bytes = (size_t)options->width * format_bpp(options->format) / 8U;
    for (unsigned int buffer_index = 0; buffer_index < 2; ++buffer_index) {
        for (unsigned int row_index = 0; row_index < options->height; ++row_index) {
            char *destination = (char *)buffers[buffer_index].map +
                                (size_t)row_index * buffers[buffer_index].pitch;
            if (fread(destination, 1, row_bytes, file) != row_bytes) {
                fprintf(stderr, "frame file %s ended before two complete frames\n",
                        options->frame_file);
                fclose(file);
                return -1;
            }
            if (buffers[buffer_index].pitch > row_bytes) {
                memset(destination + row_bytes, 0,
                       buffers[buffer_index].pitch - row_bytes);
            }
        }
    }
    if (fgetc(file) != EOF) {
        fprintf(stderr, "frame file %s contains data after two complete frames\n",
                options->frame_file);
        fclose(file);
        return -1;
    }
    fclose(file);
    return 0;
}

static int read_full_fd(int fd, void *destination, size_t size, bool allow_eof) {
    size_t offset = 0;
    while (offset < size) {
        ssize_t result = read(fd, (char *)destination + offset, size - offset);
        if (result == 0) {
            if (offset == 0 && allow_eof) {
                return 1;
            }
            return -1;
        }
        if (result < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        offset += (size_t)result;
    }
    return 0;
}

static int read_stream_header(const Options *options, size_t *frame_bytes) {
    uint8_t header[16];
    if (read_full_fd(STDIN_FILENO, header, sizeof(header), false) != 0) {
        fprintf(stderr, "continuous KMS stream ended before its header\n");
        return -1;
    }
    if (memcmp(header, STREAM_MAGIC, STREAM_MAGIC_BYTES) != 0) {
        fprintf(stderr, "continuous KMS stream has an invalid magic value\n");
        return -1;
    }
    uint32_t version = 0;
    uint32_t declared_bytes = 0;
    memcpy(&version, header + 8, sizeof(version));
    memcpy(&declared_bytes, header + 12, sizeof(declared_bytes));
    size_t row_bytes = (size_t)options->width * format_bpp(options->format) / 8U;
    size_t expected_bytes = row_bytes * (size_t)options->height;
    if (version != STREAM_VERSION || declared_bytes != expected_bytes) {
        fprintf(stderr,
                "continuous KMS stream header mismatch: version=%u bytes=%u expected=%zu\n",
                version, declared_bytes, expected_bytes);
        return -1;
    }
    *frame_bytes = expected_bytes;
    return 0;
}

static int validate_stream_patch(
    const Options *options, const DumbBuffer *buffer, bool photodiode_on
) {
    unsigned int patch_x = strstr(options->patch_corner, "left") != NULL
                               ? 0 : options->width > options->patch_size
                               ? options->width - options->patch_size : 0;
    unsigned int patch_y = strstr(options->patch_corner, "top") != NULL
                               ? 0 : options->height > options->patch_size
                               ? options->height - options->patch_size : 0;
    unsigned int value = photodiode_on ? options->patch_on : options->patch_off;
    if (options->format == DRM_FORMAT_RGB565) {
        uint16_t expected = rgb565(value, value, value);
        uint16_t actual = *(uint16_t *)((char *)buffer->map +
                                        (size_t)patch_y * buffer->pitch +
                                        (size_t)patch_x * sizeof(uint16_t));
        return actual == expected ? 0 : -1;
    }
    uint32_t expected = (value << 16) | (value << 8) | value;
    uint32_t actual = *(uint32_t *)((char *)buffer->map +
                                    (size_t)patch_y * buffer->pitch +
                                    (size_t)patch_x * sizeof(uint32_t));
    return actual == expected ? 0 : -1;
}

static int load_stream_frame(
    const Options *options,
    DumbBuffer *buffer,
    uint64_t expected_frame_index,
    uint64_t expected_producer_sequence,
    StreamFrameMetadata *metadata,
    size_t frame_bytes
) {
    uint8_t header[STREAM_FRAME_HEADER_BYTES];
    int header_result = read_full_fd(STDIN_FILENO, header, sizeof(header), true);
    if (header_result != 0) {
        if (header_result > 0) {
            return 1;
        }
        fprintf(stderr, "continuous KMS stream ended inside a frame header\n");
        return -1;
    }
    uint64_t frame_index = 0;
    uint64_t producer_sequence = 0;
    uint64_t payload_bytes = 0;
    memcpy(&frame_index, header, sizeof(frame_index));
    memcpy(&producer_sequence, header + 8, sizeof(producer_sequence));
    memcpy(&payload_bytes, header + 17, sizeof(payload_bytes));
    uint8_t photodiode = header[16];
    if (frame_index != expected_frame_index || producer_sequence != expected_producer_sequence ||
        frame_index > UINT_MAX || photodiode > 1 || payload_bytes != frame_bytes) {
        fprintf(stderr,
                "continuous KMS stream frame metadata is not contiguous or has wrong size\n");
        return -1;
    }
    size_t row_bytes = (size_t)options->width * format_bpp(options->format) / 8U;
    for (unsigned int row_index = 0; row_index < options->height; ++row_index) {
        char *destination = (char *)buffer->map + (size_t)row_index * buffer->pitch;
        if (read_full_fd(STDIN_FILENO, destination, row_bytes, false) != 0) {
            fprintf(stderr, "continuous KMS stream ended inside frame payload\n");
            return -1;
        }
        if (buffer->pitch > row_bytes) {
            memset(destination + row_bytes, 0, buffer->pitch - row_bytes);
        }
    }
    bool photodiode_on = photodiode != 0;
    if (validate_stream_patch(options, buffer, photodiode_on) != 0) {
        fprintf(stderr, "continuous KMS stream photodiode payload does not match metadata\n");
        return -1;
    }
    metadata->frame_index = frame_index;
    metadata->producer_sequence = producer_sequence;
    metadata->photodiode_on = photodiode_on;
    return 0;
}

static void interval_stats_init(IntervalStats *stats) {
    memset(stats, 0, sizeof(*stats));
    stats->minimum = HUGE_VAL;
}

static void interval_stats_add(
    IntervalStats *stats, uint64_t left_ns, uint64_t right_ns, double expected_us
) {
    if (right_ns < left_ns) {
        return;
    }
    double interval_us = (double)(right_ns - left_ns) / 1000.0;
    stats->count++;
    stats->sum += interval_us;
    if (interval_us < stats->minimum) {
        stats->minimum = interval_us;
    }
    if (interval_us > stats->maximum) {
        stats->maximum = interval_us;
    }
    double delta = interval_us - stats->mean;
    stats->mean += delta / (double)stats->count;
    stats->m2 += delta * (interval_us - stats->mean);
    if (stats->sample_count < DIAGNOSTIC_SAMPLE_CAPACITY) {
        stats->samples[stats->sample_count++] = interval_us;
    } else {
        stats->samples[stats->count % DIAGNOSTIC_SAMPLE_CAPACITY] = interval_us;
    }
    const double tolerance = 0.05;
    if (fabs(interval_us - expected_us) > expected_us * tolerance) {
        stats->outside_tolerance++;
    }
    if (interval_us > expected_us * (1.0 + tolerance)) {
        stats->long_intervals++;
        double frame_count = floor(interval_us / expected_us + 0.5);
        if (frame_count > 1.0) {
            stats->estimated_dropped += (unsigned int)frame_count - 1U;
        }
    } else if (interval_us < expected_us * (1.0 - tolerance)) {
        stats->short_intervals++;
    }
}

static void page_flip_handler(
    int fd, unsigned int frame, unsigned int seconds, unsigned int useconds, void *data
) {
    (void)fd;
    FlipState *state = data;
    uint64_t kernel_event_ns = (uint64_t)seconds * 1000000000ULL +
                               (uint64_t)useconds * 1000ULL;
    uint64_t callback_monotonic_ns = clock_ns(CLOCK_MONOTONIC);
    uint64_t callback_realtime_ns = clock_ns(CLOCK_REALTIME);
    if (state->have_previous_frame &&
        state->pending_frame.frame_index != state->previous_frame_index + 1U) {
        state->frame_indices_contiguous = false;
    }
    if (state->have_previous_kernel_sequence &&
        frame != state->previous_kernel_sequence + 1U) {
        state->kernel_sequences_contiguous = false;
    }
    if (state->completed > 0) {
        if (state->previous_kernel_event_ns != 0 && kernel_event_ns != 0) {
            interval_stats_add(
                &state->kernel_intervals,
                state->previous_kernel_event_ns,
                kernel_event_ns,
                state->expected_interval_us
            );
        }
        interval_stats_add(
            &state->callback_intervals,
            state->previous_callback_monotonic_ns,
            callback_monotonic_ns,
            state->expected_interval_us
        );
    }
    if (state->completed < state->event_capacity) {
        state->events[state->completed].frame_index = state->pending_frame.frame_index;
        state->events[state->completed].buffer_index = state->pending_frame.buffer_index;
        state->events[state->completed].photodiode_on = state->pending_frame.photodiode_on;
        state->events[state->completed].kernel_event_ns = kernel_event_ns;
        state->events[state->completed].callback_monotonic_ns = callback_monotonic_ns;
        state->events[state->completed].callback_realtime_ns = callback_realtime_ns;
        state->events[state->completed].kernel_sequence = frame;
    }
    if (state->completed == 0) {
        state->all_kernel_timestamps = kernel_event_ns != 0;
        state->first_kernel_event_ns = kernel_event_ns;
        state->first_callback_monotonic_ns = callback_monotonic_ns;
        state->first_callback_realtime_ns = callback_realtime_ns;
    } else if (kernel_event_ns == 0) {
        state->all_kernel_timestamps = false;
    }
    state->last_kernel_event_ns = kernel_event_ns;
    state->last_callback_monotonic_ns = callback_monotonic_ns;
    state->last_callback_realtime_ns = callback_realtime_ns;
    state->previous_frame_index = state->pending_frame.frame_index;
    state->previous_kernel_sequence = frame;
    state->previous_kernel_event_ns = kernel_event_ns;
    state->previous_callback_monotonic_ns = callback_monotonic_ns;
    state->have_previous_frame = true;
    state->have_previous_kernel_sequence = true;
    state->completed++;
    state->pending = false;
}

static const char *kernel_timestamp_clock(const KmsState *state) {
    if (!state->timestamp_capability_known) {
        return "unknown";
    }
    return state->timestamp_monotonic ? "monotonic" : "realtime";
}

static int wait_for_flip(KmsState *state, FlipState *flips) {
    struct pollfd pollfd = {.fd = state->fd, .events = POLLIN};
    drmEventContext context = {0};
    context.version = DRM_EVENT_CONTEXT_VERSION;
    context.page_flip_handler = page_flip_handler;
    while (flips->pending && !stop_requested) {
        int result = poll(&pollfd, 1, POLL_TIMEOUT_MS);
        if (result == 0) {
            flips->missed++;
            fprintf(stderr, "timed out waiting for page-flip event\n");
            return -1;
        }
        if (result < 0) {
            if (errno == EINTR) {
                continue;
            }
            flips->missed++;
            fprintf(stderr, "poll for page-flip event failed: %s\n", strerror(errno));
            return -1;
        }
        if (drmHandleEvent(state->fd, &context) != 0) {
            flips->missed++;
            fprintf(stderr, "drmHandleEvent failed: %s\n", strerror(errno));
            return -1;
        }
    }
    if (stop_requested) {
        flips->missed++;
        fprintf(stderr, "page-flip run interrupted\n");
        return -1;
    }
    return 0;
}

static int restore_crtc(KmsState *state) {
    if (!state->modeset_active || state->original_crtc == NULL) {
        return 0;
    }
    int result;
    if (state->original_crtc->mode_valid) {
        uint32_t connector_id = state->connector->connector_id;
        result = drmModeSetCrtc(
            state->fd,
            state->original_crtc->crtc_id,
            state->original_crtc->buffer_id,
            state->original_crtc->x,
            state->original_crtc->y,
            &connector_id,
            1,
            &state->original_crtc->mode
        );
    } else {
        result = drmModeSetCrtc(
            state->fd, state->original_crtc->crtc_id, 0, 0, 0, NULL, 0, NULL
        );
    }
    if (result != 0) {
        fprintf(stderr, "failed to restore original CRTC state: %s\n", strerror(errno));
        return -1;
    }
    state->modeset_active = false;
    return 0;
}

static void free_state(KmsState *state) {
    free(state->lease_objects);
    state->lease_objects = NULL;
    state->lease_object_count = 0;
    if (state->planes != NULL) {
        drmModeFreePlaneResources(state->planes);
        state->planes = NULL;
    }
    if (state->original_crtc != NULL) {
        drmModeFreeCrtc(state->original_crtc);
        state->original_crtc = NULL;
    }
    if (state->connector != NULL) {
        drmModeFreeConnector(state->connector);
        state->connector = NULL;
    }
    if (state->resources != NULL) {
        drmModeFreeResources(state->resources);
        state->resources = NULL;
    }
    if (state->fd >= 0) {
        close(state->fd);
        state->fd = -1;
    }
}

static int compare_double(const void *left, const void *right) {
    const double a = *(const double *)left;
    const double b = *(const double *)right;
    return a < b ? -1 : a > b ? 1 : 0;
}

static double percentile(const double *values, size_t count, double fraction) {
    if (count == 0) {
        return 0.0;
    }
    double *sorted = malloc(count * sizeof(*sorted));
    if (sorted == NULL) {
        return 0.0;
    }
    memcpy(sorted, values, count * sizeof(*sorted));
    qsort(sorted, count, sizeof(*sorted), compare_double);
    size_t index = (size_t)ceil(fraction * (double)count) - 1U;
    if (index >= count) {
        index = count - 1U;
    }
    double result = sorted[index];
    free(sorted);
    return result;
}

static void json_string(const char *value) {
    putchar('\"');
    for (const char *cursor = value; *cursor != '\0'; ++cursor) {
        if (*cursor == '\"' || *cursor == '\\') {
            putchar('\\');
        }
        putchar(*cursor);
    }
    putchar('\"');
}

static void fourcc_string(uint32_t format, char *buffer, size_t size) {
    char value[5] = {
        (char)(format & 0xff),
        (char)((format >> 8) & 0xff),
        (char)((format >> 16) & 0xff),
        (char)((format >> 24) & 0xff),
        '\0'
    };
    snprintf(buffer, size, "%s", value);
}

static void print_lease_objects_json(const KmsState *state) {
    printf("[");
    for (int index = 0; index < state->lease_object_count; ++index) {
        if (index != 0) {
            putchar(',');
        }
        printf("%u", state->lease_objects[index]);
    }
    printf("]");
}

static void print_probe_only(const Options *options, const KmsState *state) {
    if (options->json) {
        printf("{\n  \"device\": ");
        json_string(state->device);
        printf(",\n  \"connector\": ");
        json_string(options->connector);
        printf(",\n  \"connector_id\": %u,\n  \"crtc_id\": %u,\n",
               state->connector->connector_id, state->crtc_id);
        printf("  \"ownership\": \"%s\",\n  \"lease_objects\": ",
               state->lease_active ? "lease-active" : "direct");
        print_lease_objects_json(state);
        printf(",\n  \"kernel_timestamp_clock\": \"");
        printf("%s\",\n", kernel_timestamp_clock(state));
        printf("  \"selected_mode\": \"%s@%.6g\",\n  \"nominal_refresh_hz\": %.9g,\n",
               state->mode.name, mode_refresh(&state->mode), mode_refresh(&state->mode));
        printf("  \"primary_plane_id\": %u,\n  \"primary_formats\": [",
               state->primary_plane_id);
        for (uint32_t index = 0; index < state->primary_format_count; ++index) {
            char format[5];
            if (index != 0) {
                putchar(',');
            }
            fourcc_string(state->primary_formats[index], format, sizeof(format));
            json_string(format);
        }
        printf("],\n  \"access\": {\n"
               "    \"device_exists\": %s,\n"
               "    \"device_readable\": %s,\n"
               "    \"device_opened\": true,\n"
               "    \"resources_enumerated\": %s,\n"
               "    \"connector_resolved\": %s,\n"
               "    \"mode_compatible\": %s,\n"
               "    \"crtc_resolved\": %s,\n"
               "    \"primary_plane_compatible\": %s,\n"
               "    \"modeset_authority\": \"not-tested\",\n"
               "    \"page_flips\": \"not-tested\"\n"
               "  },\n  \"modeset\": false,\n  \"page_flip\": false\n}\n",
               state->device_exists ? "true" : "false",
               state->device_readable ? "true" : "false",
               state->resources_enumerated ? "true" : "false",
               state->connector_resolved ? "true" : "false",
               state->mode_compatible ? "true" : "false",
               state->crtc_resolved ? "true" : "false",
               state->primary_plane_compatible ? "true" : "false");
    } else {
        printf("device=%s connector=%s crtc=%u mode=%s@%.6g primary_plane=%u\n",
               state->device, options->connector, state->crtc_id,
               state->mode.name, mode_refresh(&state->mode), state->primary_plane_id);
        printf("ownership=%s lease_objects=", state->lease_active ? "lease-active" : "direct");
        for (int index = 0; index < state->lease_object_count; ++index) {
            if (index != 0) {
                putchar(',');
            }
            printf("%u", state->lease_objects[index]);
        }
        putchar('\n');
        printf("primary_formats=");
        for (uint32_t index = 0; index < state->primary_format_count; ++index) {
            char format[5];
            if (index != 0) {
                putchar(',');
            }
            fourcc_string(state->primary_formats[index], format, sizeof(format));
            fputs(format, stdout);
        }
        printf(" access=device_exists:%s,readable:%s,opened:true,resources:%s,connector:%s,"
               "mode:%s,crtc:%s,primary_plane:%s,modeset_authority:not-tested,page_flips:not-tested"
               " modeset=false page_flip=false\n",
               state->device_exists ? "true" : "false",
               state->device_readable ? "true" : "false",
               state->resources_enumerated ? "true" : "false",
               state->connector_resolved ? "resolved" : "missing",
               state->mode_compatible ? "compatible" : "incompatible",
               state->crtc_resolved ? "resolved" : "missing",
               state->primary_plane_compatible ? "compatible" : "missing");
    }
}

static void print_access_state(const KmsState *state, const char *modeset_authority,
                               const char *page_flips) {
    fprintf(stderr,
            "DRM access state: device_exists=%s readable=%s opened=%s resources=%s "
            "connector=%s mode=%s crtc=%s primary_plane=%s modeset_authority=%s page_flips=%s\n",
            state->device_exists ? "true" : "false",
            state->device_readable ? "true" : "false",
            state->fd >= 0 ? "true" : "false",
            state->resources_enumerated ? "enumerated" : "unavailable",
            state->connector_resolved ? "resolved" : "unresolved",
            state->mode_compatible ? "compatible" : "incompatible",
            state->crtc_resolved ? "resolved" : "unresolved",
            state->primary_plane_compatible ? "compatible" : "unavailable",
            modeset_authority, page_flips);
}

static void print_result(
    const Options *options,
    const KmsState *state,
    const FlipState *flips,
    bool restored,
    bool aborted
) {
    uint64_t completed = flips->completed;
    bool use_kernel_timestamps = completed > 0 && flips->all_kernel_timestamps;
    const char *timing_source = use_kernel_timestamps
                                    ? "kernel_event"
                                    : "callback_monotonic";
    const IntervalStats *stats = use_kernel_timestamps
                                     ? &flips->kernel_intervals
                                     : &flips->callback_intervals;
    size_t interval_count = stats->sample_count;
    const double interval_tolerance = 0.05;
    double mean = stats->count == 0 ? 0.0 : stats->mean;
    double stddev = stats->count == 0 ? 0.0 : sqrt(stats->m2 / (double)stats->count);
    double estimated_refresh = mean == 0.0 ? 0.0 : 1000000.0 / mean;
    if (options->json) {
        printf("{\n  \"device\": ");
        json_string(state->device);
        printf(",\n  \"connector\": ");
        json_string(options->connector);
        printf(",\n  \"connector_id\": %u,\n  \"crtc_id\": %u,\n",
               state->connector->connector_id, state->crtc_id);
        printf("  \"ownership\": \"%s\",\n  \"lease_objects\": ",
               state->lease_active ? "lease-active" : "direct");
        print_lease_objects_json(state);
        printf(",\n");
        printf("  \"requested_mode\": \"%ux%u@%.6g\",\n",
               options->width, options->height, options->refresh);
        printf("  \"selected_mode\": \"%s@%.6g\",\n",
               state->mode.name, mode_refresh(&state->mode));
        printf("  \"access\": {\"device_opened\": true, \"resources_enumerated\": true, "
               "\"connector_resolved\": true, \"mode_compatible\": true, "
               "\"crtc_resolved\": true, \"primary_plane_compatible\": true, "
               "\"modeset_authority\": \"acquired\", \"page_flips\": \"completed\"},\n");
        printf("  \"nominal_refresh_hz\": %.9g,\n  \"timing_source\": ",
               mode_refresh(&state->mode));
        json_string(timing_source);
        printf(",\n  \"kernel_timestamp_clock\": ");
        json_string(kernel_timestamp_clock(state));
        printf(",\n  \"pixel_format\": ");
        json_string(options->format_name);
        printf(",\n  \"requested_frame_count\": %" PRIu64 ",\n  \"completed_frame_count\": %" PRIu64 ",\n",
               options->stream ? completed : (uint64_t)options->frames, completed);
        printf("  \"first_page_flip_kernel_event_ns\": %" PRIu64 ",\n",
               flips->first_kernel_event_ns);
        printf("  \"last_page_flip_kernel_event_ns\": %" PRIu64 ",\n",
               flips->last_kernel_event_ns);
        printf("  \"first_page_flip_callback_monotonic_ns\": %" PRIu64 ",\n",
               flips->first_callback_monotonic_ns);
        printf("  \"last_page_flip_callback_monotonic_ns\": %" PRIu64 ",\n",
               flips->last_callback_monotonic_ns);
        printf("  \"first_page_flip_callback_realtime_ns\": %" PRIu64 ",\n",
               flips->first_callback_realtime_ns);
        printf("  \"last_page_flip_callback_realtime_ns\": %" PRIu64 ",\n",
               flips->last_callback_realtime_ns);
        printf("  \"mean_vblank_interval_us\": %.6f,\n  \"std_vblank_interval_us\": %.6f,\n",
               mean, stddev);
        printf("  \"minimum_vblank_interval_us\": %.6f,\n  \"maximum_vblank_interval_us\": %.6f,\n",
               stats->count ? stats->minimum : 0.0, stats->maximum);
        printf("  \"p95_vblank_interval_us\": %.6f,\n  \"p99_vblank_interval_us\": %.6f,\n",
               percentile(stats->samples, interval_count, 0.95),
               percentile(stats->samples, interval_count, 0.99));
        printf("  \"estimated_refresh_hz\": %.9g,\n"
               "  \"interval_tolerance_fraction\": %.6g,\n"
               "  \"intervals_outside_tolerance\": %u,\n"
               "  \"long_interval_count\": %u,\n"
               "  \"short_interval_count\": %u,\n"
               "  \"estimated_dropped_frame_count\": %u,\n",
               estimated_refresh, interval_tolerance, stats->outside_tolerance,
               stats->long_intervals, stats->short_intervals, stats->estimated_dropped);
        printf("  \"photodiode\": {\"corner\": ");
        json_string(options->patch_corner);
        printf(", \"size_px\": %u, \"on_value\": %u, \"off_value\": %u, "
               "\"frame_state\": ",
               options->patch_size, options->patch_on, options->patch_off);
        json_string(options->stream
                        ? "stream_metadata"
                        : "logical_frame_0=on,logical_frame_1=off,initial_modeset=off_preroll");
        printf("},\n");
        printf("  \"frame_source\": ");
        json_string(options->stream
                        ? "continuous-packed-stream"
                        : options->frame_file == NULL ? "synthetic-alternating" : "external-raw-pair");
        printf(",\n");
        printf("  \"missed_vblank_count\": %u,\n"
               "  \"frame_index_contiguous\": %s,\n"
               "  \"kernel_sequence_contiguous\": %s,\n"
               "  \"photodiode_metadata_valid\": %s,\n"
               "  \"estimated_doubled_frame_count\": %u,\n"
               "  \"aborted\": %s,\n  \"restored\": %s,\n",
               flips->missed,
               flips->frame_indices_contiguous ? "true" : "false",
               flips->kernel_sequences_contiguous ? "true" : "false",
               flips->photodiode_metadata_valid ? "true" : "false",
               stats->short_intervals,
               aborted ? "true" : "false", restored ? "true" : "false");
        printf("  \"ownership_lifecycle\": {\"lease_acquire_count\": %u,"
               " \"modeset_count\": 1, \"restore_count\": %u,"
               " \"lease_release_count\": %u},\n",
               options->lease ? 1U : 0U, restored ? 1U : 0U, options->lease ? 1U : 0U);
        printf("  \"flip_event_count\": %" PRIu64 ",\n  \"flip_events_stored\": %u,\n"
               "  \"flip_trace_truncated\": %s,\n",
               completed,
               flips->event_capacity < completed ? flips->event_capacity : (unsigned int)completed,
               flips->event_capacity < completed ? "true" : "false");
        printf("  \"flip_events\": [");
        unsigned int stored_events = flips->event_capacity < completed
                                         ? flips->event_capacity
                                         : (unsigned int)completed;
        for (unsigned int index = 0; index < stored_events; ++index) {
            if (index != 0) {
                putchar(',');
            }
            printf("{\"frame_index\":%u,\"buffer_index\":%u,\"photodiode_state\":\"%s\","
                   "\"kernel_sequence\":%u,\"kernel_event_ns\":%" PRIu64
                   ",\"callback_monotonic_ns\":%" PRIu64
                   ",\"callback_realtime_ns\":%" PRIu64 "}",
                   flips->events[index].frame_index,
                   flips->events[index].buffer_index,
                   flips->events[index].photodiode_on ? "on" : "off",
                   flips->events[index].kernel_sequence,
                   flips->events[index].kernel_event_ns,
                   flips->events[index].callback_monotonic_ns,
                   flips->events[index].callback_realtime_ns);
        }
        printf("]\n}\n");
    } else {
        printf("device=%s connector=%s crtc=%u mode=%s@%.6g format=%s\n",
               state->device, options->connector, state->crtc_id,
               state->mode.name, mode_refresh(&state->mode), options->format_name);
        printf("frames=%" PRIu64 "/%" PRIu64 " source=%s kernel_clock=%s mean_us=%.3f p95_us=%.3f p99_us=%.3f min_us=%.3f max_us=%.3f "
               "estimated_hz=%.6f outside_tolerance=%u long_intervals=%u short_intervals=%u "
               "estimated_dropped=%u missed=%u restored=%s aborted=%s\n",
               completed, options->stream ? completed : (uint64_t)options->frames,
               timing_source, kernel_timestamp_clock(state), mean,
               percentile(stats->samples, interval_count, 0.95),
               percentile(stats->samples, interval_count, 0.99),
               stats->count ? stats->minimum : 0.0, stats->maximum, estimated_refresh,
               stats->outside_tolerance, stats->long_intervals, stats->short_intervals,
               stats->estimated_dropped,
               flips->missed, restored ? "true" : "false", aborted ? "true" : "false");
    }
}

static void usage(const char *program) {
    fprintf(stderr,
            "usage: %s [options]\n"
            "  --device PATH       DRM card; omitted scans /dev/dri/card*\n"
            "  --connector NAME    explicit connector (default HDMI-A-1)\n"
            "  --width PX          requested width (default 1024)\n"
            "  --height PX         requested height (default 600)\n"
            "  --refresh HZ        requested refresh (default 59.82)\n"
            "  --tolerance HZ      refresh tolerance (default 0.05)\n"
            "  --format NAME       RGB565 or XRGB8888 (default RGB565)\n"
            "  --frames N          synchronous page flips (default 120)\n"
            "  --patch-corner NAME top_left/top_right/bottom_left/bottom_right\n"
            "  --patch-size PX     photodiode patch size (default 50)\n"
            "  --patch-on VALUE    photodiode on value (default 255)\n"
            "  --patch-off VALUE   photodiode off value (default 0)\n"
            "  --color R,G,B       hold background color while toggling patch\n"
            "  --frame-file PATH   two packed frames, even/on then odd/off\n"
            "  --stream            read one continuous packed frame stream from stdin\n"
            "  --lease             acquire a Wayland DRM lease for the connector\n"
            "  --lease-discover    enumerate lease offers without requesting a lease\n"
            "  --probe-only        enumerate resources without modesetting\n"
            "  --json              emit machine-readable result\n",
            program);
}

static void print_lease_discovery(
    const Options *options, const DrmLeaseDiscovery *discovery
) {
    if (options->json) {
        printf("{\n  \"ownership\": \"lease-available\",\n");
        printf("  \"requested_connector\": \"%s\",\n", options->connector);
        printf("  \"drm_fd_received\": %s,\n",
               discovery->drm_fd_received ? "true" : "false");
        printf("  \"offers\": [");
        for (unsigned int index = 0; index < discovery->offer_count; ++index) {
            const DrmLeaseOffer *offer = &discovery->offers[index];
            printf("%s{\"name\":\"%s\",\"connector_id\":%u,\"withdrawn\":%s}",
                   index == 0 ? "" : ",",
                   offer->name,
                   offer->connector_id,
                   offer->withdrawn ? "true" : "false");
        }
        printf("]\n}\n");
        return;
    }
    printf("lease discovery: requested=%s drm_fd_received=%s offers=%u\n",
           options->connector,
           discovery->drm_fd_received ? "true" : "false",
           discovery->offer_count);
    for (unsigned int index = 0; index < discovery->offer_count; ++index) {
        const DrmLeaseOffer *offer = &discovery->offers[index];
        printf("  %s connector_id=%u withdrawn=%s\n",
               offer->name,
               offer->connector_id,
               offer->withdrawn ? "true" : "false");
    }
}

static int parse_color(const char *value, unsigned int color[3]) {
    unsigned int red, green, blue;
    if (sscanf(value, "%u,%u,%u", &red, &green, &blue) != 3 ||
        red > 255 || green > 255 || blue > 255) {
        return -1;
    }
    color[0] = red;
    color[1] = green;
    color[2] = blue;
    return 0;
}

int main(int argc, char **argv) {
    Options options = {
        .connector = "HDMI-A-1",
        .width = 1024,
        .height = 600,
        .refresh = 59.82,
        .tolerance = 0.05,
        .format = DRM_FORMAT_RGB565,
        .format_name = "RGB565",
        .frames = 120,
        .patch_size = 50,
        .patch_on = 255,
        .patch_off = 0,
        .patch_corner = "bottom_right",
    };
    static const struct option long_options[] = {
        {"device", required_argument, NULL, 'd'},
        {"connector", required_argument, NULL, 'c'},
        {"width", required_argument, NULL, 'w'},
        {"height", required_argument, NULL, 'h'},
        {"refresh", required_argument, NULL, 'r'},
        {"tolerance", required_argument, NULL, 't'},
        {"format", required_argument, NULL, 'f'},
        {"frames", required_argument, NULL, 'n'},
        {"patch-corner", required_argument, NULL, 'q'},
        {"patch-size", required_argument, NULL, 'p'},
        {"patch-on", required_argument, NULL, 'a'},
        {"patch-off", required_argument, NULL, 'b'},
        {"color", required_argument, NULL, 'o'},
        {"frame-file", required_argument, NULL, 'F'},
        {"stream", no_argument, NULL, 's'},
        {"lease", no_argument, NULL, 'L'},
        {"lease-discover", no_argument, NULL, 'D'},
        {"probe-only", no_argument, NULL, 'P'},
        {"json", no_argument, NULL, 'j'},
        {"help", no_argument, NULL, '?'}
    };
    int option;
    while ((option = getopt_long(argc, argv, "d:c:w:h:r:t:f:n:q:p:a:b:o:F:sLDPj", long_options, NULL)) != -1) {
        char *end = NULL;
        switch (option) {
        case 'd': options.device = optarg; break;
        case 'c': options.connector = optarg; break;
        case 'w': options.width = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'h': options.height = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'r': options.refresh = strtod(optarg, &end); break;
        case 't': options.tolerance = strtod(optarg, &end); break;
        case 'n': options.frames = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'q': options.patch_corner = optarg; break;
        case 'p': options.patch_size = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'a': options.patch_on = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'b': options.patch_off = (unsigned int)strtoul(optarg, &end, 10); break;
        case 'f':
            options.format = format_from_name(optarg);
            options.format_name = optarg;
            break;
        case 'o':
            if (parse_color(optarg, options.color) != 0) {
                fprintf(stderr, "invalid --color; expected R,G,B with values 0..255\n");
                return 2;
            }
            options.color_set = true;
            break;
        case 'F': options.frame_file = optarg; break;
        case 's': options.stream = true; break;
        case 'L': options.lease = true; break;
        case 'D': options.lease_discover = true; break;
        case 'P': options.probe_only = true; break;
        case 'j': options.json = true; break;
        case '?': usage(argv[0]); return 0;
        default: usage(argv[0]); return 2;
        }
        if (end != NULL && *end != '\0') {
            fprintf(stderr, "invalid numeric option value: %s\n", optarg);
            return 2;
        }
    }
    if (options.format == 0 || options.width == 0 || options.height == 0 ||
        options.refresh <= 0.0 || options.tolerance < 0.0 ||
        (!options.stream && (options.frames == 0 || options.frames > MAX_FRAMES)) ||
        options.patch_size == 0 ||
        options.patch_on > 255 || options.patch_off > 255 ||
        (strcmp(options.patch_corner, "top_left") != 0 &&
         strcmp(options.patch_corner, "top_right") != 0 &&
         strcmp(options.patch_corner, "bottom_left") != 0 &&
         strcmp(options.patch_corner, "bottom_right") != 0)) {
        fprintf(stderr, "invalid KMS probe options\n");
        return 2;
    }
    if (options.lease && options.device != NULL) {
        fprintf(stderr, "--lease cannot be combined with --device; the lease supplies its DRM fd\n");
        return 2;
    }
    if (options.lease_discover && options.lease) {
        fprintf(stderr, "--lease-discover cannot be combined with --lease\n");
        return 2;
    }
    if (options.lease_discover && options.device != NULL) {
        fprintf(stderr, "--lease-discover cannot be combined with --device\n");
        return 2;
    }
    if (options.stream && (options.frame_file != NULL || options.color_set || options.probe_only)) {
        fprintf(stderr, "--stream cannot be combined with --frame-file, --color, or --probe-only\n");
        return 2;
    }

    if (options.lease_discover) {
        DrmLeaseDiscovery discovery = {0};
        char discovery_error[256] = {0};
        if (drm_lease_discover(
                options.connector, &discovery, discovery_error, sizeof(discovery_error)) != 0) {
            fprintf(stderr, "DRM lease discovery failed: %s\n", discovery_error);
            return 1;
        }
        print_lease_discovery(&options, &discovery);
        return 0;
    }

    KmsState state = {.fd = -1};
    FlipState flips = {
        .all_kernel_timestamps = true,
        .frame_indices_contiguous = true,
        .kernel_sequences_contiguous = true,
        .photodiode_metadata_valid = true,
    };
    DumbBuffer buffers[2] = {0};
    DrmLease lease = {.fd = -1, .state = DRM_LEASE_FAILED};
    bool restored = false;
    bool aborted = false;
    int exit_code = 1;
    install_signal_handlers();
    interval_stats_init(&flips.kernel_intervals);
    interval_stats_init(&flips.callback_intervals);

    if (options.lease) {
        char lease_error[256] = {0};
        if (drm_lease_acquire(options.connector, &lease, lease_error, sizeof(lease_error)) != 0) {
            fprintf(stderr, "DRM lease acquisition failed: %s\n", lease_error);
            goto cleanup;
        }
        int leased_fd = drm_lease_take_fd(&lease);
        if (leased_fd < 0 || inspect_state_fd(&options, &state, leased_fd, "wayland-drm-lease") != 0 ||
            validate_lease_objects(&state) != 0) {
            fprintf(stderr, "DRM lease resource validation failed\n");
            goto cleanup;
        }
    } else if (discover_device(&options, &state) != 0) {
        goto cleanup;
    }
    if (options.probe_only) {
        print_probe_only(&options, &state);
        exit_code = 0;
        goto cleanup;
    }
    /* Keep a bounded presentation trace for streamed natural-image runs.  The
     * payload is useful for mapping image/gray boundaries to actual DRM
     * callback timestamps without retaining stimulus pixels in native memory. */
    flips.event_capacity = options.stream ? STREAM_EVENT_CAPACITY : options.frames;
    if (flips.event_capacity > 0) {
        flips.events = calloc(flips.event_capacity, sizeof(*flips.events));
        if (flips.events == NULL) {
            fprintf(stderr, "cannot allocate bounded flip-event buffer\n");
            goto cleanup;
        }
    }
    flips.expected_interval_us = 1000000.0 / mode_refresh(&state.mode);
    size_t stream_frame_bytes = 0;
    if (options.stream && read_stream_header(&options, &stream_frame_bytes) != 0) {
        goto cleanup;
    }
    if (create_dumb_buffer(&options, &state, &buffers[0]) != 0 ||
        create_dumb_buffer(&options, &state, &buffers[1]) != 0) {
        goto cleanup;
    }
    StreamFrameMetadata stream_metadata[2] = {0};
    if (options.stream) {
        if (load_stream_frame(&options, &buffers[0], 0, 0, &stream_metadata[0], stream_frame_bytes) != 0 ||
            load_stream_frame(&options, &buffers[1], 1, 1, &stream_metadata[1], stream_frame_bytes) != 0) {
            fprintf(stderr, "continuous KMS stream requires at least two complete frames\n");
            goto cleanup;
        }
    } else if (options.frame_file == NULL) {
        fill_buffer(&options, &buffers[0], 0);
        fill_buffer(&options, &buffers[1], 1);
    } else if (load_frame_file(&options, buffers) != 0) {
        goto cleanup;
    }
    if (drmModeSetCrtc(state.fd, state.crtc_id,
                       buffers[kms_preroll_buffer_index()].framebuffer, 0, 0,
                       &state.connector->connector_id, 1, &state.mode) != 0) {
        int set_errno = errno;
        if (set_errno == EACCES || set_errno == EPERM) {
            fprintf(stderr,
                    "DRM device is accessible but another session/compositor currently owns "
                    "modesetting authority (DRM master); run outside that compositor or use "
                    "a DRM lease\n");
            print_access_state(&state, "denied", "not-tested");
        } else {
            fprintf(stderr, "initial drmModeSetCrtc failed: %s\n", strerror(set_errno));
            print_access_state(&state, "failed", "not-tested");
        }
        goto cleanup;
    }
    state.modeset_active = true;
    if (options.stream) {
        uint64_t frame = 0;
        while (true) {
            StreamFrameMetadata *metadata = &stream_metadata[frame % 2U];
            flips.pending_frame = (KmsFrameMetadata){
                .frame_index = (unsigned int)metadata->frame_index,
                .buffer_index = (unsigned int)(frame % 2U),
                .photodiode_on = metadata->photodiode_on,
            };
            flips.pending = true;
            if (drmModePageFlip(
                    state.fd,
                    state.crtc_id,
                    buffers[flips.pending_frame.buffer_index].framebuffer,
                    DRM_MODE_PAGE_FLIP_EVENT, &flips) != 0) {
                flips.missed++;
                int flip_errno = errno;
                fprintf(stderr, "continuous KMS page flip failed at frame %" PRIu64 ": %s\n",
                        frame, strerror(flip_errno));
                flips.pending = false;
                goto cleanup;
            }
            if (wait_for_flip(&state, &flips) != 0) {
                goto cleanup;
            }
            if (frame == 0) {
                frame = 1;
                continue;
            }
            int next_frame_result = load_stream_frame(
                    &options,
                    &buffers[(frame + 1U) % 2U],
                    frame + 1U,
                    frame + 1U,
                    &stream_metadata[(frame + 1U) % 2U],
                    stream_frame_bytes
                );
            if (next_frame_result != 0) {
                if (next_frame_result > 0) {
                    break;
                }
                goto cleanup;
            }
            frame++;
        }
    } else for (unsigned int frame = 0; frame < options.frames; ++frame) {
        flips.pending_frame = kms_frame_metadata(frame);
        flips.pending = true;
        if (drmModePageFlip(
                state.fd,
                state.crtc_id,
                buffers[flips.pending_frame.buffer_index].framebuffer,
                DRM_MODE_PAGE_FLIP_EVENT, &flips) != 0) {
            flips.missed++;
            int flip_errno = errno;
            if (flip_errno == EACCES || flip_errno == EPERM) {
                fprintf(stderr,
                        "DRM page flip rejected because modesetting authority was lost "
                        "to another session/compositor\n");
                print_access_state(&state, "lost", "denied");
            } else {
                fprintf(stderr, "drmModePageFlip failed at frame %u: %s\n",
                        frame, strerror(flip_errno));
                print_access_state(&state, "acquired", "failed");
            }
            flips.pending = false;
            goto cleanup;
        }
        if (wait_for_flip(&state, &flips) != 0) {
            goto cleanup;
        }
    }
    if (restore_crtc(&state) != 0) {
        goto cleanup;
    }
    restored = true;
    print_result(&options, &state, &flips, restored, aborted);
    exit_code = 0;

cleanup:
    if (stop_requested) {
        aborted = true;
    }
    if (state.modeset_active) {
        if (restore_crtc(&state) == 0) {
            restored = true;
        }
    }
    destroy_dumb_buffer(&state, &buffers[1]);
    destroy_dumb_buffer(&state, &buffers[0]);
    if (exit_code != 0 && options.json) {
        fprintf(stderr, "KMS probe failed; restored=%s completed=%" PRIu64 "\n",
                restored ? "true" : "false", flips.completed);
    }
    free(flips.events);
    free_state(&state);
    if (options.lease) {
        char lease_error[256] = {0};
        if (drm_lease_release(&lease, lease_error, sizeof(lease_error)) != 0) {
            fprintf(stderr, "DRM lease/compositor recovery failed: %s\n", lease_error);
            exit_code = 1;
        }
    }
    return exit_code;
}
