"""Global pytest fixtures and configuration."""

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block external network connections during unit tests unless marked with @pytest.mark.live."""
    if "live" in request.keywords:
        return

    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: tuple[str, int] | str | bytes) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "localhost", "::1"):
            real_connect(self, address)
            return
        raise RuntimeError(
            f"Network access disabled in unit tests (attempted connection to {host!r}). "
            "Mark test with @pytest.mark.live to allow."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
