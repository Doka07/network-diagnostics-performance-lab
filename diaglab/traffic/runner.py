"""Owned Linux iperf3 client with bounded output and verified process-group cleanup."""

import ipaddress
import math
import os
import selectors
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from diaglab.artifacts.store import ArtifactStore
from diaglab.exceptions import (
    ArtifactIntegrityError,
    FaultCleanupError,
    SafetyPreflightError,
)
from diaglab.models import RunContext, TrafficHandle, TrafficResult
from diaglab.serialization import parse_json

STDOUT_LIMIT = 16 * 1024 * 1024
STDERR_LIMIT = 1024 * 1024
READ_QUERY_TIMEOUT_S = 2.0


def _bounded_query(argv: list[str]) -> bytes:
    process = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        for name in output:
            pipe = getattr(process, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        deadline = time.monotonic() + READ_QUERY_TIMEOUT_S
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise SafetyPreflightError("read-only host query timed out")
            for key, _ in selector.select(timeout=min(0.05, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(output[key.data]) + len(chunk) > STDERR_LIMIT:
                    raise SafetyPreflightError("read-only host query exceeds 1 MiB")
                output[key.data].extend(chunk)
        try:
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise SafetyPreflightError("read-only host query timed out") from exc
        if process.returncode:
            raise SafetyPreflightError("read-only host query failed")
        return bytes(output["stdout"])
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        for name in output:
            getattr(process, name).close()


def resolve_source(context: RunContext) -> str:
    data = context.config.to_dict()
    target = data["target"]
    try:
        addresses = parse_json(_bounded_query(["ip", "-j", "-4", "address", "show"]).decode())
        routes = parse_json(
            _bounded_query(["ip", "-j", "-4", "route", "get", target["host"]]).decode()
        )
        if not isinstance(addresses, list) or not isinstance(routes, list) or len(routes) != 1:
            raise SafetyPreflightError("unexpected live interface/route query result")
        route = routes[0]
        if route.get("dev") != target["interface"] or route.get("gateway"):
            raise SafetyPreflightError("target must use the selected direct LAN interface")
        source = route.get("prefsrc", route.get("src"))
        owned = []
        all_addresses = set()
        for interface in addresses:
            for entry in interface.get("addr_info", []):
                if entry.get("family") != "inet":
                    continue
                address = ipaddress.IPv4Interface(f"{entry['local']}/{entry['prefixlen']}")
                all_addresses.add(address.ip)
                if interface.get("ifname") == target["interface"]:
                    owned.append(address)
        peer = ipaddress.IPv4Address(target["host"])
        if peer in all_addresses or peer.is_multicast or peer.is_unspecified or peer.is_loopback:
            raise SafetyPreflightError("target must be a distinct unicast LAN peer")
        for address in owned:
            if str(address.ip) == source and peer in address.network:
                if peer in (address.network.network_address, address.network.broadcast_address):
                    raise SafetyPreflightError("target is a subnet network/broadcast address")
                return source
        raise SafetyPreflightError("source/target identity does not match interface prefix")
    except (OSError, ValueError, KeyError, TypeError, ArtifactIntegrityError) as exc:
        raise SafetyPreflightError(f"cannot verify live route/interface identity: {exc}") from exc


def probe_server(context: RunContext, source: str) -> None:
    target = context.config.data["target"]
    try:
        # Bare TCP connect, no application protocol or hidden transfer.
        with socket.create_connection(
            (target["host"], target["port"]),
            timeout=float(context.config.data["traffic"]["connect_timeout_s"]),
            source_address=(source, 0),
        ):
            pass
    except OSError as exc:
        raise SafetyPreflightError(f"SERVER_UNREACHABLE: {exc}") from exc


def execution_deadline_s(context: RunContext) -> float:
    traffic = context.config.data["traffic"]
    return float(
        sum(
            traffic[key]
            for key in ("connect_timeout_s", "omit_s", "duration_s", "finish_timeout_s")
        )
    )


def client_command(context: RunContext, executable: str, source: str) -> list[str]:
    data = context.config.data
    target, traffic = data["target"], data["traffic"]
    return [
        executable,
        "-c",
        target["host"],
        "-B",
        source,
        "-p",
        str(target["port"]),
        "-t",
        str(traffic["duration_s"]),
        "-P",
        str(traffic["streams"]),
        "-O",
        str(traffic["omit_s"]),
        "-J",
        "--get-server-output",
        "--connect-timeout",
        str(math.ceil(traffic["connect_timeout_s"] * 1000)),
    ]


@dataclass
class _Owned:
    context: RunContext
    handle: TrafficHandle
    process: subprocess.Popen
    store: ArtifactStore
    stdout_file: object
    stderr_file: object
    selector: selectors.BaseSelector
    sizes: dict[str, int] = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    result: TrafficResult | None = None
    failure: str | None = None
    timed_out: bool = False
    cleaned: bool = False
    closed: bool = False
    cleanup_error: FaultCleanupError | None = None


class Iperf3TrafficAdapter:
    name = "iperf3"

    def __init__(self, *, executable: str = "iperf3") -> None:
        self.executable = executable
        self.context: RunContext | None = None
        self.source: str | None = None
        self.resolved_executable: str | None = None
        self.command: tuple[str, ...] = ()
        self._owned: dict[int, _Owned] = {}

    def prepare(self, context: RunContext) -> None:
        if self.context is not None or self._owned:
            raise SafetyPreflightError("adapter is already prepared; use a new adapter per run")
        data = context.config.data
        if (
            data["scenario"]["kind"] != "baseline"
            or data["evidence_kind"] != "pilot"
            or data["traffic"]["streams"] not in (1, 4)
            or data["safety"]["dry_run"]
            or not data["safety"]["approved_profile_id"]
        ):
            raise SafetyPreflightError(
                "live adapter requires approved baseline pilot configuration"
            )
        executable = shutil.which(self.executable)
        if executable is None:
            raise SafetyPreflightError("iperf3 executable unavailable")
        source = resolve_source(context)
        with ArtifactStore(context.artifact_root) as store:
            for name in ("client.json", "client.stderr"):
                if name in store.names():
                    raise SafetyPreflightError("raw traffic artifacts already exist")
        probe_server(context, source)
        self.context = context
        self.source = source
        self.resolved_executable = str(Path(executable).absolute())
        self.command = tuple(client_command(context, self.resolved_executable, source))

    def start(self, context: RunContext) -> TrafficHandle:
        if context is not self.context or self._owned:
            raise SafetyPreflightError("start requires this adapter's prepared context")
        store = ArtifactStore(context.artifact_root)
        stdout_file = stderr_file = process = None
        selector = selectors.DefaultSelector()
        try:
            stdout_file = store.open_new("client.json")
            stderr_file = store.open_new("client.stderr")
            started = time.monotonic_ns()
            process = subprocess.Popen(
                list(self.command),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            handle = TrafficHandle(process.pid, process.pid, started)
            for name in ("stdout", "stderr"):
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            owned = _Owned(context, handle, process, store, stdout_file, stderr_file, selector)
            self._owned[id(handle)] = owned
            return handle
        except BaseException:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
            selector.close()
            for file in (stdout_file, stderr_file):
                if file is not None:
                    file.flush()
                    os.fsync(file.fileno())
                    file.close()
            store.close()
            raise

    def _lookup(self, handle: TrafficHandle) -> _Owned:
        owned = self._owned.get(id(handle))
        if owned is None or owned.handle is not handle:
            raise SafetyPreflightError("refusing unknown process handle")
        return owned

    @staticmethod
    def _group_alive(owned: _Owned) -> bool:
        try:
            os.killpg(owned.handle.process_group_id, 0)
            return True
        except ProcessLookupError:
            return False

    @staticmethod
    def _drain(owned: _Owned, timeout: float = 0.0) -> None:
        for key, _ in owned.selector.select(timeout):
            try:
                chunk = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                owned.selector.unregister(key.fileobj)
                continue
            name = key.data
            limit = STDOUT_LIMIT if name == "stdout" else STDERR_LIMIT
            remaining = max(0, limit - owned.sizes[name])
            getattr(owned, name + "_file").write(chunk[:remaining])
            owned.sizes[name] += min(len(chunk), remaining)
            if len(chunk) > remaining:
                owned.failure = "OUTPUT_LIMIT_EXCEEDED"

    def _close(self, owned: _Owned) -> None:
        if owned.closed:
            return
        failure = None
        try:
            for name in ("stdout", "stderr"):
                file = getattr(owned, name + "_file")
                try:
                    file.flush()
                    os.fsync(file.fileno())
                except OSError as exc:
                    failure = exc
                finally:
                    file.close()
                    getattr(owned.process, name).close()
            owned.selector.close()
            os.fsync(owned.store.directory)
        finally:
            owned.store.close()
            owned.closed = True
        if failure is not None:
            raise ArtifactIntegrityError(
                f"traffic output durability failed: {failure}"
            ) from failure

    def stop(self, handle: TrafficHandle) -> None:
        owned = self._lookup(handle)
        if owned.cleaned:
            return
        if owned.cleanup_error is not None:
            raise owned.cleanup_error
        try:
            owned.process.poll()  # Reap the direct child before group-existence checks.
            if self._group_alive(owned):
                try:
                    os.killpg(handle.process_group_id, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = (
                    time.monotonic() + owned.context.config.data["traffic"]["terminate_grace_s"]
                )
                while time.monotonic() < deadline:
                    self._drain(owned, min(0.02, max(0, deadline - time.monotonic())))
                    owned.process.poll()
                    if not self._group_alive(owned):
                        break
                if self._group_alive(owned):
                    try:
                        os.killpg(handle.process_group_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                self._drain(owned, min(0.02, max(0, deadline - time.monotonic())))
                owned.process.poll()
                if not self._group_alive(owned) and not owned.selector.get_map():
                    break
            if self._group_alive(owned):
                raise FaultCleanupError("owned traffic process group remains after escalation")
            owned.process.wait(timeout=max(0.001, deadline - time.monotonic()))
            owned.cleaned = True
        except (OSError, subprocess.TimeoutExpired, FaultCleanupError) as exc:
            owned.cleanup_error = (
                exc
                if isinstance(exc, FaultCleanupError)
                else FaultCleanupError(f"traffic cleanup could not be verified: {exc}")
            )
        finally:
            try:
                self._close(owned)
            except (OSError, ArtifactIntegrityError):
                if owned.cleanup_error is None:
                    raise
        if owned.cleanup_error is not None:
            raise owned.cleanup_error

    def wait(self, handle: TrafficHandle) -> TrafficResult:
        owned = self._lookup(handle)
        if owned.result is not None:
            return owned.result
        deadline = handle.started_monotonic_ns / 1e9 + execution_deadline_s(owned.context)
        try:
            while not owned.closed:
                self._drain(owned, min(0.02, max(0, deadline - time.monotonic())))
                returncode = owned.process.poll()
                if owned.failure:
                    break
                if returncode is not None and not owned.selector.get_map():
                    break
                if time.monotonic() >= deadline:
                    owned.timed_out = True
                    owned.failure = "EXECUTION_DEADLINE_EXCEEDED"
                    break
        finally:
            self.stop(handle)
        returncode = owned.process.returncode
        timeout_stage = "execution" if owned.timed_out else None
        if returncode and owned.failure is None:
            owned.failure = "PROCESS_NONZERO_EXIT"
            try:
                with ArtifactStore(owned.context.artifact_root) as store:
                    record = parse_json(store.read("client.json").decode("utf-8"))
                error = record.get("error", "") if isinstance(record, dict) else ""
                if isinstance(error, str) and "connect" in error.lower():
                    if "timed out" in error.lower() or "timeout" in error.lower():
                        owned.failure = "CONNECTION_TIMED_OUT"
                        timeout_stage = "connect"
                    elif "refused" in error.lower():
                        owned.failure = "CONNECTION_REFUSED"
            except (ArtifactIntegrityError, UnicodeError):
                pass
        owned.result = TrafficResult(
            returncode,
            "client.json",
            "client.stderr",
            owned.timed_out,
            timeout_stage,
            owned.cleaned,
            owned.failure,
        )
        return owned.result
