#include "drm_lease.h"

#include <assert.h>

int main(void) {
    assert(drm_lease_protocol_selfcheck() == 0);
    return 0;
}
