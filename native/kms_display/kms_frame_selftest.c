#include <assert.h>

#include "frame_semantics.h"

static void assert_frame_prefix(unsigned int completed) {
    for (unsigned int frame_index = 0; frame_index < completed; ++frame_index) {
        KmsFrameMetadata metadata = kms_frame_metadata(frame_index);
        assert(metadata.frame_index == frame_index);
        assert(metadata.buffer_index == frame_index % 2U);
        assert(metadata.photodiode_on == (frame_index % 2U == 0U));
    }
}

int main(void) {
    for (unsigned int frame_count = 1; frame_count <= 8; ++frame_count) {
        assert_frame_prefix(frame_count);
    }
    /* An early interruption records only this completed prefix. */
    assert_frame_prefix(3);

    /* --frame-file loads the external pair into the same on/off buffers. */
    assert(kms_preroll_buffer_index() == 1U);
    assert(kms_frame_metadata(0).buffer_index == 0U);
    assert(kms_frame_metadata(0).photodiode_on);
    assert(kms_frame_metadata(1).buffer_index == 1U);
    assert(!kms_frame_metadata(1).photodiode_on);
    return 0;
}
