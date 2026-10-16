"""Small ownership lifecycle model for the native DRM lease boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeaseState(str, Enum):
    COMPOSITOR_MANAGED = "compositor-managed"
    LEASE_AVAILABLE = "lease-available"
    LEASE_REQUESTED = "lease-requested"
    LEASE_ACTIVE = "lease-active"
    LEASE_REVOKED = "lease-revoked"
    RELEASING = "releasing"
    COMPOSITOR_RESTORED = "compositor-restored"
    FAILED = "failed"


class LeaseError(RuntimeError):
    """Raised when the lease lifecycle cannot proceed safely."""


@dataclass(frozen=True)
class LeaseConnector:
    name: str
    connector_id: int
    withdrawn: bool = False


@dataclass
class LeaseLifecycle:
    offers: tuple[LeaseConnector, ...] = ()
    state: LeaseState = LeaseState.COMPOSITOR_MANAGED
    selected: LeaseConnector | None = None
    lease_fd: int | None = None
    error: str | None = None
    _requested_name: str | None = field(default=None, repr=False)

    @classmethod
    def from_offers(cls, offers: tuple[LeaseConnector, ...]) -> LeaseLifecycle:
        return cls(offers=offers, state=LeaseState.LEASE_AVAILABLE)

    def withdraw(self, connector: str) -> None:
        self.offers = tuple(
            LeaseConnector(item.name, item.connector_id, True) if item.name == connector else item
            for item in self.offers
        )

    def select_exact(self, connector: str) -> LeaseConnector:
        matches = [item for item in self.offers if item.name == connector]
        if len(matches) > 1:
            raise LeaseError(f"ambiguous DRM lease connector: {connector}")
        if not matches:
            raise LeaseError(f"DRM lease connector is unavailable: {connector}")
        if matches[0].withdrawn:
            raise LeaseError(f"lease connector was withdrawn before request: {connector}")
        self.selected = matches[0]
        self._requested_name = connector
        self.state = LeaseState.LEASE_REQUESTED
        return matches[0]

    def activate(self, lease_fd: int) -> None:
        if self.state != LeaseState.LEASE_REQUESTED:
            raise LeaseError("lease was activated before a request")
        if lease_fd < 0:
            self.state = LeaseState.FAILED
            self.error = "lease fd failure"
            raise LeaseError(self.error)
        self.lease_fd = lease_fd
        self.state = LeaseState.LEASE_ACTIVE

    def deny(self, reason: str = "lease denied") -> None:
        self.state = LeaseState.FAILED
        self.error = reason

    def revoke(self) -> None:
        self.state = LeaseState.LEASE_REVOKED
        self.lease_fd = None

    def disconnect(self) -> None:
        self.state = LeaseState.FAILED
        self.error = "compositor disconnected"
        self.lease_fd = None

    def release(self) -> None:
        if self.state not in {LeaseState.LEASE_ACTIVE, LeaseState.LEASE_REVOKED}:
            raise LeaseError("cannot release an inactive lease")
        self.state = LeaseState.RELEASING
        self.lease_fd = None

    def restored(self) -> None:
        if self.state != LeaseState.RELEASING:
            raise LeaseError("compositor restoration was not requested")
        self.state = LeaseState.COMPOSITOR_RESTORED
