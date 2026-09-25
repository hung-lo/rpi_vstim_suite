#define _GNU_SOURCE

#include "drm_lease.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct wl_display;
struct wl_proxy;
struct wl_message;
struct wl_interface {
    const char *name;
    int version;
    int method_count;
    const struct wl_message *methods;
    int event_count;
    const struct wl_message *events;
};
struct wl_message {
    const char *name;
    const char *signature;
    const struct wl_interface *const *types;
};

extern struct wl_display *wl_display_connect(const char *name);
extern void wl_display_disconnect(struct wl_display *display);
extern int wl_display_roundtrip(struct wl_display *display);
extern int wl_display_get_error(struct wl_display *display);
extern struct wl_proxy *wl_proxy_marshal_flags(
    struct wl_proxy *, uint32_t, const struct wl_interface *, uint32_t, uint32_t, ...
);
extern int wl_proxy_add_listener(struct wl_proxy *, void (**implementation)(void), void *data);
extern const struct wl_interface wl_registry_interface;

#define WL_MARSHAL_FLAG_DESTROY 1U

static const struct wl_interface lease_request_interface;
static const struct wl_interface lease_interface;
static const struct wl_interface lease_connector_interface;
static const struct wl_interface lease_device_interface;

static const struct wl_interface *const device_method_types[] = {
    &lease_request_interface,
};
static const struct wl_interface *const device_event_types[] = {
    NULL,
    &lease_connector_interface,
};
static const struct wl_interface *const request_method_types[] = {
    &lease_connector_interface,
    &lease_interface,
};

static const struct wl_message device_methods[] = {
    {"create_lease_request", "n", device_method_types},
    {"release", "", NULL},
};
static const struct wl_message device_events[] = {
    {"drm_fd", "h", NULL},
    {"connector", "n", device_event_types + 1},
    {"done", "", NULL},
    {"released", "", NULL},
};
static const struct wl_message request_methods[] = {
    {"request_connector", "o", request_method_types},
    {"submit", "n", request_method_types + 1},
};
static const struct wl_message lease_events[] = {
    {"lease_fd", "h", NULL},
    {"finished", "", NULL},
};
static const struct wl_message connector_events[] = {
    {"name", "s", NULL},
    {"description", "s", NULL},
    {"connector_id", "u", NULL},
    {"done", "", NULL},
    {"withdrawn", "", NULL},
};
static const struct wl_message lease_destroy_methods[] = {
    {"destroy", "", NULL},
};

/* Keep these counts aligned with drm-lease-v1.xml: event opcodes follow requests. */
static const struct wl_interface lease_request_interface = {
    "wp_drm_lease_request_v1", 1, 2, request_methods, 0, NULL
};
static const struct wl_interface lease_interface = {
    "wp_drm_lease_v1", 1, 1, lease_destroy_methods, 2, lease_events
};
static const struct wl_interface lease_connector_interface = {
    "wp_drm_lease_connector_v1", 1, 1, lease_destroy_methods, 5, connector_events
};
static const struct wl_interface lease_device_interface = {
    "wp_drm_lease_device_v1", 1, 2, device_methods, 4, device_events
};

typedef struct {
    struct wl_proxy *proxy;
    char name[64];
    uint32_t connector_id;
    bool complete;
    bool withdrawn;
} ConnectorOffer;

typedef struct {
    struct wl_display *display;
    struct wl_proxy *device;
    struct wl_proxy *lease_object;
    DrmLease *owner;
    ConnectorOffer offers[DRM_LEASE_MAX_OFFERS];
    unsigned int offer_count;
    uint32_t device_global;
    uint32_t device_version;
    int drm_fd;
    int lease_fd;
    bool drm_fd_received;
    bool device_done;
    bool device_released;
    bool lease_finished;
    char last_state[64];
} LeaseContext;

static void set_error(char *error, size_t error_size, const char *format, ...) {
    if (error == NULL || error_size == 0) {
        return;
    }
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, error_size, format, arguments);
    va_end(arguments);
}

static void debug_log(const char *format, ...) {
    const char *enabled = getenv("RPI_VSTIM_DRM_LEASE_DEBUG");
    if (enabled == NULL || enabled[0] == '\0' || strcmp(enabled, "0") == 0) {
        return;
    }
    va_list arguments;
    va_start(arguments, format);
    fputs("DRM lease: ", stderr);
    vfprintf(stderr, format, arguments);
    fputc('\n', stderr);
    va_end(arguments);
}

static void debug_state(LeaseContext *context, const char *state) {
    snprintf(context->last_state, sizeof(context->last_state), "%s", state);
    debug_log("state=%s", context->last_state);
}

static void connector_name_event(void *data, struct wl_proxy *proxy, const char *name) {
    (void)proxy;
    snprintf(
        ((ConnectorOffer *)data)->name,
        sizeof(((ConnectorOffer *)data)->name),
        "%s",
        name == NULL ? "" : name
    );
    debug_log("connector name=%s", ((ConnectorOffer *)data)->name);
}

static void connector_id_event(void *data, struct wl_proxy *proxy, uint32_t connector_id) {
    (void)proxy;
    ((ConnectorOffer *)data)->connector_id = connector_id;
    debug_log("connector id=%u", connector_id);
}

static void connector_description_event(void *data, struct wl_proxy *proxy, const char *description) {
    (void)data;
    (void)proxy;
    (void)description;
}

static void connector_done_event(void *data, struct wl_proxy *proxy) {
    (void)proxy;
    ((ConnectorOffer *)data)->complete = true;
    debug_log("connector done name=%s", ((ConnectorOffer *)data)->name);
}

static void connector_withdrawn_event(void *data, struct wl_proxy *proxy) {
    ConnectorOffer *offer = data;
    offer->withdrawn = true;
    debug_log("connector withdrawn name=%s id=%u", offer->name, offer->connector_id);
    wl_proxy_marshal_flags(proxy, 0, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
}

static const struct {
    void (*name)(void *, struct wl_proxy *, const char *);
    void (*description)(void *, struct wl_proxy *, const char *);
    void (*connector_id)(void *, struct wl_proxy *, uint32_t);
    void (*done)(void *, struct wl_proxy *);
    void (*withdrawn)(void *, struct wl_proxy *);
} connector_listener = {
    connector_name_event,
    connector_description_event,
    connector_id_event,
    connector_done_event,
    connector_withdrawn_event,
};

static void device_drm_fd_event(void *data, struct wl_proxy *proxy, int fd) {
    (void)proxy;
    LeaseContext *context = data;
    if (context->drm_fd >= 0) {
        close(fd);
        return;
    }
    context->drm_fd = fd;
    context->drm_fd_received = true;
    debug_state(context, "discovery-drm-fd-received");
}

static void device_connector_event(
    void *data, struct wl_proxy *proxy, struct wl_proxy *connector
) {
    (void)proxy;
    LeaseContext *context = data;
    if (context->offer_count >= DRM_LEASE_MAX_OFFERS) {
        wl_proxy_marshal_flags(connector, 0, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
        return;
    }
    ConnectorOffer *offer = &context->offers[context->offer_count++];
    offer->proxy = connector;
    debug_state(context, "connector-object-created");
    if (wl_proxy_add_listener(connector, (void (**)(void))&connector_listener, offer) < 0) {
        wl_proxy_marshal_flags(connector, 0, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
        context->offer_count--;
    }
}

static void device_done_event(void *data, struct wl_proxy *proxy) {
    (void)proxy;
    ((LeaseContext *)data)->device_done = true;
    debug_state(data, "device-done");
}

static void device_released_event(void *data, struct wl_proxy *proxy) {
    (void)proxy;
    ((LeaseContext *)data)->device_released = true;
    debug_state(data, "device-released");
}

static const struct {
    void (*drm_fd)(void *, struct wl_proxy *, int);
    void (*connector)(void *, struct wl_proxy *, struct wl_proxy *);
    void (*done)(void *, struct wl_proxy *);
    void (*released)(void *, struct wl_proxy *);
} device_listener = {
    device_drm_fd_event,
    device_connector_event,
    device_done_event,
    device_released_event,
};

static void lease_fd_event(void *data, struct wl_proxy *proxy, int fd) {
    (void)proxy;
    LeaseContext *context = data;
    if (context->lease_fd >= 0) {
        close(fd);
        return;
    }
    context->lease_fd = fd;
    debug_state(context, "lease-fd-received");
}

static void lease_finished_event(void *data, struct wl_proxy *proxy) {
    (void)proxy;
    LeaseContext *context = data;
    context->lease_finished = true;
    debug_state(context, "lease-finished");
    if (context->owner != NULL) {
        context->owner->revoked = true;
        context->owner->state = DRM_LEASE_REVOKED;
    }
}

static const struct {
    void (*lease_fd)(void *, struct wl_proxy *, int);
    void (*finished)(void *, struct wl_proxy *);
} lease_listener = {
    lease_fd_event,
    lease_finished_event,
};

static void registry_global_event(
    void *data, struct wl_proxy *registry, uint32_t name, const char *interface, uint32_t version
) {
    (void)registry;
    LeaseContext *context = data;
    if (strcmp(interface, "wp_drm_lease_device_v1") == 0 && context->device_global == 0) {
        context->device_global = name;
        context->device_version = version > 1 ? 1 : version;
        debug_log("global device=%u version=%u", name, context->device_version);
    }
}

static void registry_global_remove_event(void *data, struct wl_proxy *registry, uint32_t name) {
    (void)registry;
    LeaseContext *context = data;
    if (name == context->device_global) {
        context->device_global = 0;
    }
}

static const struct {
    void (*global)(void *, struct wl_proxy *, uint32_t, const char *, uint32_t);
    void (*global_remove)(void *, struct wl_proxy *, uint32_t);
} registry_listener = {
    registry_global_event,
    registry_global_remove_event,
};

static int roundtrip(LeaseContext *context, char *error, size_t error_size) {
    if (wl_display_roundtrip(context->display) < 0 || wl_display_get_error(context->display) != 0) {
        set_error(error, error_size, "Wayland compositor disconnected during DRM lease operation");
        return -1;
    }
    return 0;
}

static ConnectorOffer *select_offer(
    LeaseContext *context, const char *connector, char *error, size_t error_size
) {
    ConnectorOffer *selected = NULL;
    for (unsigned int index = 0; index < context->offer_count; ++index) {
        ConnectorOffer *offer = &context->offers[index];
        if (strcmp(offer->name, connector) != 0) {
            continue;
        }
        if (offer->withdrawn) {
            set_error(error, error_size, "lease connector was withdrawn before request: %s", connector);
            return NULL;
        }
        if (!offer->complete) {
            set_error(error, error_size, "lease connector was not fully enumerated: %s", connector);
            return NULL;
        }
        if (selected != NULL) {
            set_error(error, error_size, "ambiguous DRM lease connector: %s", connector);
            return NULL;
        }
        selected = offer;
    }
    if (selected == NULL) {
        set_error(error, error_size, "DRM lease connector is unavailable: %s", connector);
    }
    return selected;
}

static void context_discard(LeaseContext *context) {
    if (context == NULL) {
        return;
    }
    if (context->lease_fd >= 0) {
        close(context->lease_fd);
    }
    if (context->drm_fd >= 0) {
        close(context->drm_fd);
    }
    if (context->display != NULL) {
        wl_display_disconnect(context->display);
    }
    free(context);
}

static int context_release(LeaseContext *context, char *error, size_t error_size) {
    if (context == NULL) {
        return 0;
    }
    int result = 0;
    if (context->lease_object != NULL) {
        debug_state(context, "lease-releasing");
        wl_proxy_marshal_flags(context->lease_object, 0, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
        context->lease_object = NULL;
    }
    if (context->device != NULL) {
        /* release is acknowledged by the server-side released destructor event. */
        wl_proxy_marshal_flags(context->device, 1, NULL, 1, 0);
        debug_state(context, "device-release-requested");
        if (roundtrip(context, error, error_size) != 0) {
            result = -1;
        } else if (!context->device_released) {
            set_error(error, error_size, "DRM lease device did not acknowledge release");
            result = -1;
        }
    }
    context_discard(context);
    return result;
}

static LeaseContext *context_open(char *error, size_t error_size) {
    LeaseContext *context = calloc(1, sizeof(*context));
    if (context == NULL) {
        set_error(error, error_size, "cannot allocate DRM lease context");
        return NULL;
    }
    context->drm_fd = -1;
    context->lease_fd = -1;
    context->display = wl_display_connect(NULL);
    if (context->display == NULL) {
        set_error(error, error_size, "cannot connect to the Wayland compositor");
        context_discard(context);
        return NULL;
    }
    struct wl_proxy *registry = wl_proxy_marshal_flags(
        (struct wl_proxy *)context->display, 1, &wl_registry_interface, 1, 0, NULL
    );
    if (registry == NULL || wl_proxy_add_listener(
            registry, (void (**)(void))&registry_listener, context) < 0 ||
        roundtrip(context, error, error_size) != 0 || context->device_global == 0) {
        if (error == NULL || error[0] == '\0') {
            set_error(error, error_size, "Wayland compositor does not expose DRM leasing");
        }
        context_discard(context);
        return NULL;
    }
    context->device = wl_proxy_marshal_flags(
        registry,
        0,
        &lease_device_interface,
        context->device_version,
        0,
        context->device_global,
        "wp_drm_lease_device_v1",
        context->device_version,
        NULL
    );
    if (context->device == NULL || wl_proxy_add_listener(
            context->device, (void (**)(void))&device_listener, context) < 0 ||
        roundtrip(context, error, error_size) != 0 || !context->device_done ||
        !context->drm_fd_received) {
        if (error == NULL || error[0] == '\0') {
            set_error(error, error_size, "DRM lease device did not enumerate connectors");
        }
        context_discard(context);
        return NULL;
    }
    debug_state(context, "lease-device-bound");
    return context;
}

int drm_lease_discover(
    const char *connector,
    DrmLeaseDiscovery *discovery,
    char *error,
    size_t error_size
) {
    if (connector == NULL || connector[0] == '\0' || discovery == NULL) {
        set_error(error, error_size, "invalid DRM lease discovery arguments");
        return -1;
    }
    if (error != NULL && error_size > 0) {
        error[0] = '\0';
    }
    memset(discovery, 0, sizeof(*discovery));
    LeaseContext *context = context_open(error, error_size);
    if (context == NULL) {
        return -1;
    }
    discovery->drm_fd_received = context->drm_fd_received;
    discovery->offer_count = context->offer_count;
    for (unsigned int index = 0; index < context->offer_count; ++index) {
        snprintf(
            discovery->offers[index].name,
            sizeof(discovery->offers[index].name),
            "%s",
            context->offers[index].name
        );
        discovery->offers[index].connector_id = context->offers[index].connector_id;
        discovery->offers[index].withdrawn = context->offers[index].withdrawn;
    }
    ConnectorOffer *selected = select_offer(context, connector, error, error_size);
    if (selected == NULL) {
        context_release(context, NULL, 0);
        return -1;
    }
    debug_log("target connector selected name=%s id=%u", connector, selected->connector_id);
    char release_error[256] = {0};
    int result = context_release(context, release_error, sizeof(release_error));
    if (result != 0 && (error == NULL || error[0] == '\0')) {
        set_error(error, error_size, "%s", release_error);
    }
    return result;
}

int drm_lease_acquire(const char *connector, DrmLease *lease, char *error, size_t error_size) {
    if (lease == NULL || connector == NULL || connector[0] == '\0') {
        set_error(error, error_size, "invalid DRM lease arguments");
        return -1;
    }
    if (error != NULL && error_size > 0) {
        error[0] = '\0';
    }
    memset(lease, 0, sizeof(*lease));
    lease->fd = -1;
    lease->state = DRM_LEASE_FAILED;

    LeaseContext *context = context_open(error, error_size);
    if (context == NULL) {
        return -1;
    }
    lease->state = DRM_LEASE_AVAILABLE;
    ConnectorOffer *offer = select_offer(context, connector, error, error_size);
    if (offer == NULL) {
        context_discard(context);
        return -1;
    }
    debug_log("target connector selected name=%s id=%u", connector, offer->connector_id);

    lease->state = DRM_LEASE_REQUESTED;
    struct wl_proxy *request = wl_proxy_marshal_flags(
        context->device, 0, &lease_request_interface, 1, 0, NULL
    );
    if (request == NULL) {
        set_error(error, error_size, "cannot create DRM lease request");
        goto failed;
    }
    debug_state(context, "request-created");
    wl_proxy_marshal_flags(request, 0, NULL, 1, 0, offer->proxy);
    debug_state(context, "connector-attached");
    context->lease_object = wl_proxy_marshal_flags(
        request, 1, &lease_interface, 1, WL_MARSHAL_FLAG_DESTROY, NULL
    );
    debug_state(context, "request-submitted");
    if (context->lease_object == NULL || wl_proxy_add_listener(
            context->lease_object, (void (**)(void))&lease_listener, context) < 0 ||
        roundtrip(context, error, error_size) != 0) {
        if (error == NULL || error[0] == '\0') {
            set_error(error, error_size, "DRM lease request failed");
        }
        goto failed;
    }
    if (context->lease_fd < 0 || context->lease_finished) {
        set_error(error, error_size, "DRM lease denied for connector %s", connector);
        goto failed;
    }
    lease->fd = context->lease_fd;
    context->lease_fd = -1;
    lease->connector_id = offer->connector_id;
    snprintf(lease->connector, sizeof(lease->connector), "%s", connector);
    lease->state = DRM_LEASE_ACTIVE;
    lease->context = context;
    context->owner = lease;
    lease->revoked = false;
    return 0;

failed:
    {
        char cleanup_error[256] = {0};
        context_release(context, cleanup_error, sizeof(cleanup_error));
    }
    return -1;
}

int drm_lease_take_fd(DrmLease *lease) {
    if (lease == NULL || lease->state != DRM_LEASE_ACTIVE) {
        return -1;
    }
    int fd = lease->fd;
    lease->fd = -1;
    return fd;
}

int drm_lease_release(DrmLease *lease, char *error, size_t error_size) {
    if (lease == NULL || lease->context == NULL) {
        return 0;
    }
    LeaseContext *context = lease->context;
    lease->state = DRM_LEASE_RELEASING;
    if (lease->fd >= 0) {
        close(lease->fd);
        lease->fd = -1;
    }
    int result = context_release(context, error, error_size);
    lease->context = NULL;
    lease->state = result == 0 ? DRM_LEASE_COMPOSITOR_RESTORED : DRM_LEASE_FAILED;
    return result;
}

int drm_lease_protocol_selfcheck(void) {
    return lease_device_interface.method_count == 2 &&
           lease_device_interface.event_count == 4 &&
           lease_connector_interface.method_count == 1 &&
           lease_connector_interface.event_count == 5 &&
           lease_request_interface.method_count == 2 &&
           lease_interface.method_count == 1 &&
           lease_interface.event_count == 2 ? 0 : -1;
}

const char *drm_lease_state_name(DrmLeaseState state) {
    switch (state) {
    case DRM_LEASE_AVAILABLE: return "lease-available";
    case DRM_LEASE_REQUESTED: return "lease-requested";
    case DRM_LEASE_ACTIVE: return "lease-active";
    case DRM_LEASE_REVOKED: return "lease-revoked";
    case DRM_LEASE_RELEASING: return "releasing";
    case DRM_LEASE_COMPOSITOR_RESTORED: return "compositor-restored";
    default: return "failed";
    }
}
