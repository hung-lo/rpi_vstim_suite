"""Lazy placeholder for the future direct DRM/KMS backend."""


class KmsDisplayBackend:
    name = "kms"

    def open(self, config):
        raise NotImplementedError("Pi 5 DRM/KMS implementation starts after Phase 00")

