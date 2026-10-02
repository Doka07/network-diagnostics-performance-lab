"""Run-directory matrix for independent GUI steps 1-2 tests (TG-01..TG-12).

Every "real" run here is produced by the accepted Phase 2 `run_experiment` driving a
small mock iperf3 executable, so the viewer is tested against directories the backend
actually writes, not hand-assembled ones. Tampered variants are derived from those.

Captured fixtures (tests/fixtures/iperf3) are regression data only, never performance
evidence (see provenance.json). Their RFC 5737 documentation addresses are substituted at
test time with RFC 1918 test addresses because experiment configs require RFC 1918
targets; the original private addresses are not restored and no numeric value changes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from diaglab.config import ExperimentConfig
from diaglab.run import RunInterrupted, run_experiment
from diaglab.traffic import runner as runner_module
from diaglab.traffic.runner import Iperf3TrafficAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "iperf3"
SOURCE_IP = "10.99.0.10"
TARGET_IP = "10.99.0.20"
TARGET_PORT = 5201

MOCK = """#!/usr/bin/env python3
import json, os, signal, sys, time
report = os.environ.get("MOCK_SIGNAL_REPORT")
if report:
    # Record the signal state this executed child inherited (AUD-01).
    status = {}
    if os.path.exists("/proc/self/status"):
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("SigBlk", "SigIgn"):
                    status[key] = int(value.strip(), 16)
    status["pthread_sigmask"] = sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, []))
    with open(report, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
behavior = os.environ.get("MOCK_BEHAVIOR")
if behavior == "ignore_sigterm":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if behavior in ("hang", "ignore_sigterm"):
    time.sleep(30)
    sys.exit(0)
with open(os.environ["MOCK_DOC"], encoding="utf-8") as handle:
    sys.stdout.write(handle.read())
sys.exit(int(os.environ.get("MOCK_RC", "0")))
"""

PAYLOADS = (
    "manifest.json",
    "config.json",
    "command.json",
    "events.jsonl",
    "checksums.json",
    "client.json",
    "client.stderr",
    "traffic_summary.json",
)


def captured_text(name: str) -> str:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return text.replace("192.0.2.10", SOURCE_IP).replace("192.0.2.20", TARGET_IP)


def config_dict(
    base: dict[str, Any], *, duration_s: float, streams: int, omit_s: float = 0
) -> dict[str, Any]:
    data = copy.deepcopy(base)
    data["target"]["host"] = TARGET_IP
    data["target"]["port"] = TARGET_PORT
    data["safety"]["dry_run"] = False
    data["safety"]["approved_profile_id"] = "test-profile-gui"
    data["traffic"].update(duration_s=duration_s, streams=streams, omit_s=omit_s)
    return data


def synthetic_document(
    *,
    streams: int = 4,
    retained: int = 5,
    omitted: int = 0,
    with_server: bool = True,
    with_sum: bool = True,
    with_rtt: bool = True,
    gap_after: int | None = None,
    flow_without_seconds: int | None = None,
    sum_offset_s: float = 0.0,
) -> dict[str, Any]:
    """A self-consistent forward-TCP iperf3 client document.

    Receiver bytes are deliberately smaller than sender bytes in every interval so that a
    chart built from the wrong direction is distinguishable from goodput (R-3). Server
    socket IDs differ from client socket IDs so remapping by endpoint identity is exercised.
    """
    client_ids = [5 + 2 * index for index in range(streams)]
    server_ids = [4 + 2 * index for index in range(streams)]
    ports = [41000 + index for index in range(streams)]

    def sent_bytes(socket_index: int, interval: int) -> int:
        return 100_000_000 + 1_000_003 * socket_index + 7_919 * interval

    def recv_bytes(socket_index: int, interval: int) -> int:
        return sent_bytes(socket_index, interval) - 65_536 - 13 * interval

    def windows() -> list[tuple[float, float, bool]]:
        rows = [(float(i), float(i + 1), True) for i in range(omitted)]
        shift = 0.0
        for i in range(retained):
            if gap_after is not None and i == gap_after:
                shift = 0.5
            rows.append((i + shift, i + 1 + shift, False))
        return rows

    def interval_doc(side: str) -> list[dict[str, Any]]:
        ids = client_ids if side == "client" else server_ids
        count = sent_bytes if side == "client" else recv_bytes
        epochs = []
        for number, (start, end, is_omitted) in enumerate(windows()):
            rows = []
            for index, socket_id in enumerate(ids):
                value = count(index, number)
                row: dict[str, Any] = {
                    "socket": socket_id,
                    "start": start,
                    "end": end,
                    "seconds": end - start,
                    "bytes": value,
                    "bits_per_second": value * 8 / (end - start),
                    "omitted": is_omitted,
                    "sender": side == "client",
                }
                if side == "client":
                    row["retransmits"] = index
                    if with_rtt:
                        row["rtt"] = 400 + 10 * index + number
                        row["rttvar"] = 25 + index
                rows.append(row)
            epoch: dict[str, Any] = {"streams": rows}
            if with_sum:
                total = sum(row["bytes"] for row in rows)
                # sum_offset_s shifts the aggregate window within the parser's 1e-6 s
                # tolerance; the parser takes the aggregate window from `sum` (CORE-1).
                epoch["sum"] = {
                    "start": start + sum_offset_s,
                    "end": end + sum_offset_s,
                    "seconds": end - start,
                    "bytes": total,
                    "bits_per_second": total * 8 / (end - start),
                    "omitted": is_omitted,
                    "sender": side == "client",
                }
            epochs.append(epoch)
        return epochs

    def totals(count: Callable[[int, int], int], index: int) -> int:
        offset = omitted
        return sum(count(index, offset + i) for i in range(retained))

    end_time = float(retained) + (0.5 if gap_after is not None else 0.0)

    def total_record(value: int, *, sender: bool, extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "start": 0.0,
            "end": end_time,
            "seconds": end_time,
            "bytes": value,
            "bits_per_second": value * 8 / end_time,
            "sender": sender,
            **extra,
        }

    test_start = {
        "protocol": "TCP",
        "num_streams": streams,
        "omit": omitted,
        "duration": retained,
        "reverse": 0,
        "bidir": 0,
    }
    client_streams = []
    for index, socket_id in enumerate(client_ids):
        rtt = (
            {"max_rtt": 520 + index, "min_rtt": 380 + index, "mean_rtt": 450 + index}
            if with_rtt
            else {}
        )
        client_streams.append(
            {
                "sender": total_record(
                    totals(sent_bytes, index),
                    sender=True,
                    extra={"socket": socket_id, "retransmits": index, **rtt},
                ),
                "receiver": total_record(
                    totals(recv_bytes, index), sender=False, extra={"socket": socket_id}
                ),
            }
        )
    if flow_without_seconds is not None:
        # One flow's sender total omits `seconds`: a per-flow quality flag for R-10.
        del client_streams[flow_without_seconds]["sender"]["seconds"]
    sent_total = sum(totals(sent_bytes, i) for i in range(streams))
    recv_total = sum(totals(recv_bytes, i) for i in range(streams))
    document: dict[str, Any] = {
        "start": {
            "connected": [
                {
                    "socket": socket_id,
                    "local_host": SOURCE_IP,
                    "local_port": ports[index],
                    "remote_host": TARGET_IP,
                    "remote_port": TARGET_PORT,
                }
                for index, socket_id in enumerate(client_ids)
            ],
            "version": "iperf 3.16 (synthetic)",
            "system_info": "synthetic-test-fixture",
            "test_start": test_start,
        },
        "intervals": interval_doc("client"),
        "end": {
            "streams": client_streams,
            "sum_sent": total_record(
                sent_total, sender=True, extra={"retransmits": sum(range(streams))}
            ),
            "sum_received": total_record(recv_total, sender=False, extra={}),
        },
    }
    if with_server:
        document["server_output_json"] = {
            "start": {
                "connected": [
                    {
                        "socket": socket_id,
                        "local_host": TARGET_IP,
                        "local_port": TARGET_PORT,
                        "remote_host": SOURCE_IP,
                        "remote_port": ports[index],
                    }
                    for index, socket_id in enumerate(server_ids)
                ],
                "version": "iperf 3.16 (synthetic server)",
                "system_info": "synthetic-test-fixture",
                "test_start": dict(test_start),
            },
            "intervals": interval_doc("server"),
            "end": {
                "streams": [
                    {
                        "receiver": total_record(
                            totals(recv_bytes, index), sender=False, extra={"socket": socket_id}
                        )
                    }
                    for index, socket_id in enumerate(server_ids)
                ],
                "sum_received": total_record(recv_total, sender=False, extra={}),
            },
        }
    return document


class RunBuilder:
    """Creates run directories under one root using the accepted Phase 2 runner."""

    def __init__(self, root: Path, base_config: dict[str, Any]) -> None:
        self.root = root
        self.base = base_config
        self.root.mkdir(parents=True, exist_ok=True)
        self.mock = root / "mock_iperf3.py"
        self.mock.write_text(MOCK, encoding="utf-8")
        self.mock.chmod(self.mock.stat().st_mode | stat.S_IEXEC)

    def _execute(
        self,
        name: str,
        text: str,
        *,
        duration_s: float,
        streams: int,
        omit_s: float = 0,
        returncode: int = 0,
    ) -> Path:
        doc = self.root / f"{name}.input.json"
        doc.write_text(text, encoding="utf-8")
        config = ExperimentConfig.from_dict(
            config_dict(self.base, duration_s=duration_s, streams=streams, omit_s=omit_s)
        )
        saved = {key: os.environ.get(key) for key in ("MOCK_DOC", "MOCK_RC", "MOCK_BEHAVIOR")}
        saved_hooks = (runner_module.resolve_source, runner_module.probe_server)
        os.environ["MOCK_DOC"] = str(doc)
        os.environ["MOCK_RC"] = str(returncode)
        os.environ.pop("MOCK_BEHAVIOR", None)
        runner_module.resolve_source = lambda context: SOURCE_IP
        runner_module.probe_server = lambda context, source: None
        refusal = None
        try:
            run_experiment(config, self.root / name, execute=True, executable=str(self.mock))
        except Exception as exc:
            refusal = exc  # failed runs still finalize their evidence; verified by the tests
        finally:
            runner_module.resolve_source, runner_module.probe_server = saved_hooks
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        if not (self.root / name / "manifest.json").exists():
            # A preflight refusal (e.g. executing non-pilot evidence) creates no run at all;
            # never hand back a nonexistent directory as if it were a failed run.
            raise RuntimeError(f"fixture run {name!r} was not created") from refusal
        return self.root / name

    def captured_success(self) -> Path:
        return self._execute(
            "captured_success",
            captured_text("single_stream_success_client.json"),
            duration_s=30,
            streams=1,
        )

    def connection_timeout(self) -> Path:
        return self._execute(
            "connection_timeout",
            captured_text("connection_timeout_client.json"),
            duration_s=30,
            streams=1,
            returncode=1,
        )

    def synthetic(self, name: str, **options: Any) -> Path:
        document = synthetic_document(**options)
        return self._execute(
            name,
            json.dumps(document),
            duration_s=document["start"]["test_start"]["duration"],
            streams=document["start"]["test_start"]["num_streams"],
            omit_s=document["start"]["test_start"]["omit"],
        )

    def interrupted(self) -> Path:
        config = ExperimentConfig.from_dict(
            config_dict(self.base, duration_s=20, streams=1)
            | {
                "traffic": {
                    **config_dict(self.base, duration_s=20, streams=1)["traffic"],
                    "connect_timeout_s": 0.1,
                    "finish_timeout_s": 0.2,
                    "terminate_grace_s": 0.2,
                }
            }
        )
        original_start = Iperf3TrafficAdapter.start
        saved_hooks = (runner_module.resolve_source, runner_module.probe_server)
        saved_behavior = os.environ.get("MOCK_BEHAVIOR")

        def start_then_interrupt(adapter: Iperf3TrafficAdapter, context: Any) -> Any:
            handle = original_start(adapter, context)
            os.kill(os.getpid(), signal.SIGINT)
            return handle

        os.environ["MOCK_BEHAVIOR"] = "hang"
        runner_module.resolve_source = lambda context: SOURCE_IP
        runner_module.probe_server = lambda context, source: None
        Iperf3TrafficAdapter.start = start_then_interrupt  # type: ignore[method-assign]
        try:
            run_experiment(
                config, self.root / "interrupted", execute=True, executable=str(self.mock)
            )
        except RunInterrupted:
            pass
        finally:
            Iperf3TrafficAdapter.start = original_start  # type: ignore[method-assign]
            runner_module.resolve_source, runner_module.probe_server = saved_hooks
            if saved_behavior is None:
                os.environ.pop("MOCK_BEHAVIOR", None)
            else:
                os.environ["MOCK_BEHAVIOR"] = saved_behavior
        return self.root / "interrupted"

    def offline_plan(self) -> Path:
        config = ExperimentConfig.from_dict(copy.deepcopy(self.base))
        run_experiment(config, self.root / "offline_plan", execute=False)
        return self.root / "offline_plan"

    def phase1_manifest(self, config_file: Path) -> Path:
        target = self.root / "phase1_manifest"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "diaglab",
                "manifest",
                "create",
                "--config",
                str(config_file),
                "--output",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        return target


def clone(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination, symlinks=True)
    return destination


def tree_state(root: Path) -> dict[str, tuple]:
    """Entry names, content hash and non-atime metadata (R-22)."""
    import hashlib

    state: dict[str, tuple] = {"<root>": _meta(os.lstat(root))}
    for name in sorted(os.listdir(root)):
        path = root / name
        info = os.lstat(path)
        digest = None
        if stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        state[name] = (_meta(info), digest)
    return state


def _meta(info: os.stat_result) -> tuple:
    return (info.st_mode, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Independent RFC 6901 resolver (does not use any diaglab code)."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"not an RFC 6901 pointer: {pointer!r}")
    current = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
                raise ValueError(f"bad array index {token!r} in {pointer!r}")
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(f"pointer {pointer!r} descends into a scalar")
    return current


# Shared tamper/verification helpers (used by GUI and audit regressions).


def cli_verify(path: Path) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "diaglab", "verify", "--run", str(path)],
        capture_output=True,
        timeout=120,
    )
    return result.returncode


def rehash(run: Path) -> None:
    """Make checksums.json and manifest digests consistent after a deliberate edit, so a
    deeper check (config identity, events, result) is what fails, not the digest."""
    checksums = json.loads((run / "checksums.json").read_text())
    for entry in checksums["files"]:
        data = (run / entry["path"]).read_bytes()
        entry["size_bytes"] = len(data)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
    (run / "checksums.json").write_text(json.dumps(checksums))
    manifest = json.loads((run / "manifest.json").read_text())
    by_path = {entry["path"]: entry for entry in checksums["files"]}
    data = (run / "checksums.json").read_bytes()
    by_path["checksums.json"] = {
        "path": "checksums.json",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    manifest["artifacts"] = [by_path[entry["path"]] for entry in manifest["artifacts"]]
    (run / "manifest.json").write_text(json.dumps(manifest))


def edit_json(run: Path, name: str, change: Callable[[dict], None]) -> None:
    record = json.loads((run / name).read_text())
    change(record)
    (run / name).write_text(json.dumps(record))
