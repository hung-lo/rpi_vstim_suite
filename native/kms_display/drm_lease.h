#ifndef RPI_VSTIM_DRM_LEASE_H
#define RPI_VSTIM_DRM_LEASE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    DRM_LEASE_FAILED = 0,
    DRM_LEASE_AVAILABLE,
    DRM_LEASE_REQUESTED,
    DRM_LEASE_ACTIVE,
    DRM_LEASE_REVOKED,
    DRM_LEASE_RELEASING,
    DRM_LEASE_COMPOSITOR_RESTORED,
} DrmLeaseState;

typedef struct {
    int fd;
    uint32_t connector_id;
    char connector[64];
    DrmLeaseState state;
    bool revoked;
    void *context;
} DrmLease;

int drm_lease_acquire(const char *connector, DrmLease *lease, char *error, size_t error_size);
int drm_lease_take_fd(DrmLease *lease);
int drm_lease_release(DrmLease *lease, char *error, size_t error_size);
const char *drm_lease_state_name(DrmLeaseState state);

#endif
