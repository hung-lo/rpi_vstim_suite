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

#include <drm.h>
#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#include "drm_lease.h"

#define MAX_FRAMES 10000U
#define POLL_TIMEOUT_MS 2000

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
    bool color_set;
    unsigned int color[3];
} Options;

typedef struct {
    uint64_t monotonic_ns;
    uint64_t realtime_ns;
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
    drmModeModeInfo mode;
    bool mode_selected;
    bool lease_active;
    uint32_t *lease_objects;
    int lease_object_count;
    bool modeset_active;
} KmsState;

typedef struct {
    FlipEvent *events;
    unsigned int capacity;
    unsigned int completed;
    unsigned int missed;
    bool pending;
} FlipState;

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

static void page_flip_handler(
    int fd, unsigned int frame, unsigned int seconds, unsigned int useconds, void *data
) {
    (void)fd;
    (void)seconds;
    (void)useconds;
    FlipState *state = data;
    if (state->completed < state->capacity) {
        state->events[state->completed].monotonic_ns = clock_ns(CLOCK_MONOTONIC_RAW);
        state->events[state->completed].realtime_ns = clock_ns(CLOCK_REALTIME);
        state->events[state->completed].kernel_sequence = frame;
    }
    state->completed++;
    state->pending = false;
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
        printf(",\n");
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
    unsigned int completed = flips->completed > flips->capacity ? flips->capacity : flips->completed;
    size_t interval_count = completed > 1 ? completed - 1U : 0U;
    double *intervals = interval_count == 0 ? NULL : calloc(interval_count, sizeof(*intervals));
    double sum = 0.0;
    double maximum = 0.0;
    double minimum = HUGE_VAL;
    unsigned int outside = 0;
    unsigned int long_intervals = 0;
    unsigned int short_intervals = 0;
    unsigned int estimated_dropped = 0;
    const double interval_tolerance = 0.05;
    for (size_t index = 0; index < interval_count; ++index) {
        double interval = (double)(flips->events[index + 1].monotonic_ns -
                                   flips->events[index].monotonic_ns) / 1000.0;
        intervals[index] = interval;
        sum += interval;
        if (interval > maximum) {
            maximum = interval;
        }
        if (interval < minimum) {
            minimum = interval;
        }
        double expected = 1000000.0 / mode_refresh(&state->mode);
        if (fabs(interval - expected) > expected * interval_tolerance) {
            outside++;
        }
        if (interval > expected * (1.0 + interval_tolerance)) {
            long_intervals++;
            double frame_count = floor(interval / expected + 0.5);
            if (frame_count > 1.0) {
                estimated_dropped += (unsigned int)frame_count - 1U;
            }
        } else if (interval < expected * (1.0 - interval_tolerance)) {
            short_intervals++;
        }
    }
    double mean = interval_count == 0 ? 0.0 : sum / (double)interval_count;
    double variance = 0.0;
    for (size_t index = 0; index < interval_count; ++index) {
        double delta = intervals[index] - mean;
        variance += delta * delta;
    }
    double stddev = interval_count == 0 ? 0.0 : sqrt(variance / (double)interval_count);
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
        printf("  \"nominal_refresh_hz\": %.9g,\n  \"pixel_format\": ",
               mode_refresh(&state->mode));
        json_string(options->format_name);
        printf(",\n  \"requested_frame_count\": %u,\n  \"completed_frame_count\": %u,\n",
               options->frames, completed);
        printf("  \"first_page_flip_monotonic_ns\": %" PRIu64 ",\n",
               completed ? flips->events[0].monotonic_ns : 0);
        printf("  \"last_page_flip_monotonic_ns\": %" PRIu64 ",\n",
               completed ? flips->events[completed - 1U].monotonic_ns : 0);
        printf("  \"first_page_flip_realtime_ns\": %" PRIu64 ",\n",
               completed ? flips->events[0].realtime_ns : 0);
        printf("  \"mean_vblank_interval_us\": %.6f,\n  \"std_vblank_interval_us\": %.6f,\n",
               mean, stddev);
        printf("  \"minimum_vblank_interval_us\": %.6f,\n  \"maximum_vblank_interval_us\": %.6f,\n",
               interval_count ? minimum : 0.0, maximum);
        printf("  \"p95_vblank_interval_us\": %.6f,\n  \"p99_vblank_interval_us\": %.6f,\n",
               percentile(intervals, interval_count, 0.95),
               percentile(intervals, interval_count, 0.99));
        printf("  \"estimated_refresh_hz\": %.9g,\n"
               "  \"interval_tolerance_fraction\": %.6g,\n"
               "  \"intervals_outside_tolerance\": %u,\n"
               "  \"long_interval_count\": %u,\n"
               "  \"short_interval_count\": %u,\n"
               "  \"estimated_dropped_frame_count\": %u,\n",
               estimated_refresh, interval_tolerance, outside, long_intervals,
               short_intervals, estimated_dropped);
        printf("  \"photodiode\": {\"corner\": ");
        json_string(options->patch_corner);
        printf(", \"size_px\": %u, \"on_value\": %u, \"off_value\": %u, "
               "\"frame_state\": \"even=on,odd=off\"},\n",
               options->patch_size, options->patch_on, options->patch_off);
        printf("  \"missed_vblank_count\": %u,\n  \"aborted\": %s,\n  \"restored\": %s,\n",
               flips->missed, aborted ? "true" : "false", restored ? "true" : "false");
        printf("  \"flip_events\": [");
        for (unsigned int index = 0; index < completed; ++index) {
            if (index != 0) {
                putchar(',');
            }
            printf("{\"frame_index\":%u,\"kernel_sequence\":%u,\"monotonic_ns\":%" PRIu64
                   ",\"realtime_ns\":%" PRIu64 "}", index,
                   flips->events[index].kernel_sequence,
                   flips->events[index].monotonic_ns,
                   flips->events[index].realtime_ns);
        }
        printf("]\n}\n");
    } else {
        printf("device=%s connector=%s crtc=%u mode=%s@%.6g format=%s\n",
               state->device, options->connector, state->crtc_id,
               state->mode.name, mode_refresh(&state->mode), options->format_name);
        printf("frames=%u/%u mean_us=%.3f p95_us=%.3f p99_us=%.3f min_us=%.3f max_us=%.3f "
               "estimated_hz=%.6f outside_tolerance=%u long_intervals=%u short_intervals=%u "
               "estimated_dropped=%u missed=%u restored=%s aborted=%s\n",
               completed, options->frames, mean,
               percentile(intervals, interval_count, 0.95),
               percentile(intervals, interval_count, 0.99),
               interval_count ? minimum : 0.0, maximum, estimated_refresh,
               outside, long_intervals, short_intervals, estimated_dropped,
               flips->missed, restored ? "true" : "false", aborted ? "true" : "false");
    }
    free(intervals);
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
            "  --lease             acquire a Wayland DRM lease for the connector\n"
            "  --probe-only        enumerate resources without modesetting\n"
            "  --json              emit machine-readable result\n",
            program);
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
        {"lease", no_argument, NULL, 'L'},
        {"probe-only", no_argument, NULL, 'P'},
        {"json", no_argument, NULL, 'j'},
        {"help", no_argument, NULL, '?'}
    };
    int option;
    while ((option = getopt_long(argc, argv, "d:c:w:h:r:t:f:n:q:p:a:b:o:LPj", long_options, NULL)) != -1) {
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
        case 'L': options.lease = true; break;
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
        options.refresh <= 0.0 || options.tolerance < 0.0 || options.frames == 0 ||
        options.frames > MAX_FRAMES || options.patch_size == 0 ||
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

    KmsState state = {.fd = -1};
    FlipState flips = {0};
    DumbBuffer buffers[2] = {0};
    DrmLease lease = {.fd = -1, .state = DRM_LEASE_FAILED};
    bool restored = false;
    bool aborted = false;
    int exit_code = 1;
    install_signal_handlers();

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
    flips.capacity = options.frames;
    flips.events = calloc(flips.capacity, sizeof(*flips.events));
    if (flips.events == NULL) {
        fprintf(stderr, "cannot allocate bounded flip-event buffer\n");
        goto cleanup;
    }
    if (create_dumb_buffer(&options, &state, &buffers[0]) != 0 ||
        create_dumb_buffer(&options, &state, &buffers[1]) != 0) {
        goto cleanup;
    }
    fill_buffer(&options, &buffers[0], 0);
    fill_buffer(&options, &buffers[1], 1);
    if (drmModeSetCrtc(state.fd, state.crtc_id, buffers[0].framebuffer, 0, 0,
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
    for (unsigned int frame = 0; frame < options.frames; ++frame) {
        unsigned int next_buffer = frame % 2U ? 0U : 1U;
        flips.pending = true;
        if (drmModePageFlip(state.fd, state.crtc_id, buffers[next_buffer].framebuffer,
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
        fprintf(stderr, "KMS probe failed; restored=%s completed=%u\n",
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
