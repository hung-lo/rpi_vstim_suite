#ifndef RPI_VSTIM_FRAME_SEMANTICS_H
#define RPI_VSTIM_FRAME_SEMANTICS_H

#include <stdbool.h>

typedef struct {
    unsigned int frame_index;
    unsigned int buffer_index;
    bool photodiode_on;
} KmsFrameMetadata;

static inline KmsFrameMetadata kms_frame_metadata(unsigned int frame_index) {
    return (KmsFrameMetadata){
        .frame_index = frame_index,
        .buffer_index = frame_index % 2U,
        .photodiode_on = frame_index % 2U == 0U,
    };
}

static inline unsigned int kms_preroll_buffer_index(void) {
    return 1U;
}

#endif
