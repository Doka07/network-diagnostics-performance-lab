"""PRB-01–04: the live TCP preflight probe (docs/PHASE2_CONTRACTS.md, "Liveness and
receiver setup"), which every other suite monkeypatches out.

The contract says the probe is one TCP connect with no payload, that it consumes a one-off
server's accepted connection (so Phase 2 requires a persistent server), and that "tests
must cover this one-off incompatibility". The 2026-10-03 hardware pilot showed the
documented side effect on a real receiver: iperf3 logged "unable to receive cookie" for
the probe's connection before the real test. These tests call the real probe_server
against fake listeners bound to 127.0.0.1 only: no LAN traffic, no iperf3.
"""

from __future__ import annotations

import socket
import threading
from types import SimpleNamespace

import pytest

from diaglab.exceptions import SafetyPreflightError
from diaglab.traffic.runner import probe_server

LOOPBACK = "127.0.0.1"


def context_for(port: int, connect_timeout_s: float = 2.0):
    data = {
        "target": {"host": LOOPBACK, "port": port},
        "traffic": {"connect_timeout_s": connect_timeout_s},
    }
    return SimpleNamespace(config=SimpleNamespace(data=data))


class FakeReceiver:
    """Records each accepted connection's peer address and every byte it sends until EOF.
    `one_off` closes the listener after the first accept, like `iperf3 -s -1`."""

    def __init__(self, *, one_off: bool) -> None:
        self.listener = socket.create_server((LOOPBACK, 0))
        self.listener.settimeout(0.05)  # poll, so close() never waits on a blocked accept
        self.port = self.listener.getsockname()[1]
        self.one_off = one_off
        self.stopping = threading.Event()
        self.sessions: list[tuple[tuple, bytes]] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stopping.is_set():
            try:
                connection, peer = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(5)
                received = b""
                while chunk := connection.recv(4096):
                    received += chunk
                self.sessions.append((peer, received))
            if self.one_off:
                self.listener.close()
                return

    def wait_for(self, count: int) -> None:
        for _ in range(500):
            if len(self.sessions) >= count:
                return
            threading.Event().wait(0.01)
        raise AssertionError(f"expected {count} sessions, saw {len(self.sessions)}")

    def close(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)
        self.listener.close()


@pytest.fixture
def persistent():
    server = FakeReceiver(one_off=False)
    yield server
    server.close()


@pytest.fixture
def one_off():
    server = FakeReceiver(one_off=True)
    yield server
    server.close()


def test_prb01_probe_is_one_bare_connection_with_no_payload(persistent) -> None:
    probe_server(context_for(persistent.port), LOOPBACK)
    persistent.wait_for(1)
    assert len(persistent.sessions) == 1
    peer, payload = persistent.sessions[0]
    assert payload == b""  # no iperf3 cookie: the receiver's "unable to receive cookie"
    assert peer[0] == LOOPBACK  # bound to the selected source address


def test_prb02_refused_port_is_server_unreachable() -> None:
    holder = socket.create_server((LOOPBACK, 0))
    port = holder.getsockname()[1]
    holder.close()
    with pytest.raises(SafetyPreflightError, match="SERVER_UNREACHABLE"):
        probe_server(context_for(port), LOOPBACK)


def test_prb03_probe_consumes_a_one_off_server(one_off) -> None:
    """The documented incompatibility: after the probe, a one-off server no longer
    listens, so the real client's connection is refused."""
    probe_server(context_for(one_off.port), LOOPBACK)
    one_off.wait_for(1)
    one_off.thread.join(timeout=5)
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection((LOOPBACK, one_off.port), timeout=2).close()


def test_prb04_persistent_server_still_accepts_the_client(persistent) -> None:
    probe_server(context_for(persistent.port), LOOPBACK)
    with socket.create_connection((LOOPBACK, persistent.port), timeout=2) as client:
        client.sendall(b"client-session")
    persistent.wait_for(2)
    assert [payload for _, payload in persistent.sessions] == [b"", b"client-session"]
