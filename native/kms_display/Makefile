CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c11
LDFLAGS ?=

all: kms_probe drm_lease_selftest kms_frame_selftest

kms_probe: kms_probe.c drm_lease.c drm_lease.h frame_semantics.h
	$(CC) $(CFLAGS) $(shell pkg-config --cflags libdrm) -o $@ kms_probe.c drm_lease.c $(LDFLAGS) $(shell pkg-config --libs libdrm) $(shell pkg-config --libs wayland-client 2>/dev/null || echo -Wl,-l:libwayland-client.so.0) -lm

drm_lease_selftest: drm_lease_selftest.c drm_lease.c drm_lease.h
	$(CC) $(CFLAGS) -o $@ drm_lease_selftest.c drm_lease.c $(LDFLAGS) -Wl,-l:libwayland-client.so.0

kms_frame_selftest: kms_frame_selftest.c frame_semantics.h
	$(CC) $(CFLAGS) -o $@ kms_frame_selftest.c

clean:
	rm -f kms_probe drm_lease_selftest kms_frame_selftest

.PHONY: all clean
