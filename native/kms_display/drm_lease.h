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

#define DRM_LEASE_MAX_OFFERS 16U

typedef struct {
    char name[64];
    uint32_t connector_id;
    bool withdrawn;
} DrmLeaseOffer;

typedef struct {
    DrmLeaseOffer offers[DRM_LEASE_MAX_OFFERS];
    unsigned int offer_count;
    bool drm_fd_received;
} DrmLeaseDiscovery;

int drm_lease_discover(
    const char *connector,
    DrmLeaseDiscovery *discovery,
    char *error,
    size_t error_size
);
int drm_lease_acquire(const char *connector, DrmLease *lease, char *error, size_t error_size);
int drm_lease_take_fd(DrmLease *lease);
int drm_lease_release(DrmLease *lease, char *error, size_t error_size);
int drm_lease_protocol_selfcheck(void);
const char *drm_lease_state_name(DrmLeaseState state);

#endif
