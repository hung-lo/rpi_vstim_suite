import pytest

from rpi_vstim.display.lease import LeaseConnector, LeaseError, LeaseLifecycle, LeaseState


def offers():
    return LeaseLifecycle.from_offers(
        (
            LeaseConnector("HDMI-A-1", 33),
            LeaseConnector("HDMI-A-2", 42),
        )
    )


def test_exact_connector_selection_and_lifecycle():
    lease = offers()
    selected = lease.select_exact("HDMI-A-1")
    assert selected.connector_id == 33
    assert lease.state == LeaseState.LEASE_REQUESTED
    lease.activate(7)
    assert lease.state == LeaseState.LEASE_ACTIVE
    lease.release()
    lease.restored()
    assert lease.state == LeaseState.COMPOSITOR_RESTORED


def test_ambiguous_connector_is_rejected():
    lease = LeaseLifecycle.from_offers((LeaseConnector("HDMI-A-1", 33), LeaseConnector("HDMI-A-1", 99)))
    with pytest.raises(LeaseError, match="ambiguous"):
        lease.select_exact("HDMI-A-1")


def test_withdrawn_connector_is_rejected_before_request():
    lease = offers()
    lease.withdraw("HDMI-A-1")
    with pytest.raises(LeaseError, match="withdrawn"):
        lease.select_exact("HDMI-A-1")


def test_denied_revoked_disconnect_and_fd_failure_states():
    denied = offers()
    denied.select_exact("HDMI-A-1")
    denied.deny()
    assert denied.state == LeaseState.FAILED

    revoked = offers()
    revoked.select_exact("HDMI-A-1")
    revoked.activate(7)
    revoked.revoke()
    assert revoked.state == LeaseState.LEASE_REVOKED

    disconnected = offers()
    disconnected.select_exact("HDMI-A-1")
    disconnected.disconnect()
    assert disconnected.state == LeaseState.FAILED

    fd_failure = offers()
    fd_failure.select_exact("HDMI-A-1")
    with pytest.raises(LeaseError, match="fd failure"):
        fd_failure.activate(-1)
    assert fd_failure.state == LeaseState.FAILED
