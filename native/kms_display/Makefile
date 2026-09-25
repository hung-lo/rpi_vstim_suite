CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c11
LDFLAGS ?=

all: kms_probe

kms_probe: kms_probe.c drm_lease.c drm_lease.h
	$(CC) $(CFLAGS) $(shell pkg-config --cflags libdrm) -o $@ kms_probe.c drm_lease.c $(LDFLAGS) $(shell pkg-config --libs libdrm) $(shell pkg-config --libs wayland-client 2>/dev/null || echo -Wl,-l:libwayland-client.so.0) -lm

clean:
	rm -f kms_probe

.PHONY: all clean
