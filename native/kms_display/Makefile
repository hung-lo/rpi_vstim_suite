CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c11
LDFLAGS ?=

all: kms_probe

kms_probe: kms_probe.c
	$(CC) $(CFLAGS) $(shell pkg-config --cflags libdrm) -o $@ $< $(LDFLAGS) $(shell pkg-config --libs libdrm) -lm

clean:
	rm -f kms_probe

.PHONY: all clean
