"""Fixtures for LC-01–12 (docs/RECEIVER_LIFECYCLE.md), written from the contract before
reading scripts/receiver_lifecycle.py.

Every "remote" command is a real local fake executable, so process groups, pipes, signals
and timeouts are exercised for real. Nothing contacts SSH, Windows or the network. Each
fake appends its step name to a shared log, proving which steps ran after earlier failures.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
REQUIRED = ("owner.json", "server.jsonl", "server.stderr", "cleanup.json")
CONTENT = {
    "owner.json": b'{"pid": 1048, "start_ticks": 1, "executable": "iperf3.exe"}',
    "server.jsonl": b'{"start": {}, "intervals": [], "end": {}}\n',
    "server.stderr": b"synthetic receiver stderr \xe2\x9c\x93\n",
    "cleanup.json": b'{"process_gone": true, "listener_gone": true, "rule_gone": true}',
}

FAKE = r"""
import base64, hashlib, json, os, signal, subprocess, sys, time
role, behavior, work = sys.argv[1], sys.argv[2], sys.argv[3]
def log(entry):
    with open(os.path.join(work, "steps.log"), "a") as handle:
        handle.write(entry + "\n")
def spawn_grandchild(name):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    open(os.path.join(work, name + ".grandchild.pid"), "w").write(str(child.pid))
def flood():
    block = b"x" * 65536
    for _ in range(9 * 16 + 4):  # just over 9 MiB, beyond the 8 MiB bound
        sys.stdout.buffer.write(block)
    sys.stdout.buffer.flush()

if role == "session":
    open(os.path.join(work, "session.pid"), "w").write(str(os.getpid()))
    spawn_grandchild("session")
    if behavior in ("stall", "stall_ignore_term"):
        if behavior == "stall_ignore_term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(0.05)
    if behavior == "flood":
        flood()
    if behavior == "escape":  # leaves the owned group but keeps the session's stdout open
        escapee = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
        )
        open(os.path.join(work, "escapee.pid"), "w").write(str(escapee.pid))
    while not os.path.exists(os.path.join(work, "stop")):
        time.sleep(0.02)
    print("session finished")
    sys.exit(0)

log(role)
if role == "stop":
    output = os.environ.get("LC_OUTPUT", "")
    log("stop-saw-output=" + str(bool(output) and os.path.isdir(output)))
    if behavior == "hang":
        spawn_grandchild("stop")
        time.sleep(120)
    if behavior == "flood":
        flood()
    if behavior == "sigint_parent":  # an operator Ctrl-C arriving during shutdown
        os.kill(os.getppid(), signal.SIGINT)
        time.sleep(0.3)
    open(os.path.join(work, "stop"), "w").close()
    sys.exit(3 if behavior == "fail" else 0)

if role == "cleanup":
    good = {"process_gone": True, "listener_gone": True, "rule_gone": True}
    if behavior == "hang":
        spawn_grandchild("cleanup")
        time.sleep(120)
    text = {
        "ok": json.dumps(good),
        "partial": json.dumps(dict(good, rule_gone=False)),
        "extra": json.dumps(dict(good, verified=True)),
        "missing_key": json.dumps({"process_gone": True, "listener_gone": True}),
        "string_true": json.dumps(dict(good, listener_gone="true")),
        "invalid": "{not json",
        "nonzero_ok": json.dumps(good),
    }[behavior]
    print(text)
    sys.exit(4 if behavior == "nonzero_ok" else 0)

if role == "capture":
    content = json.loads(os.environ["LC_CONTENT"])
    files = {k: base64.b64decode(v) for k, v in content.items()}
    names = list(files)
    missing = []
    if behavior == "missing_listed":
        names.remove("server.stderr"); missing = ["server.stderr"]
    if behavior == "missing_silent":
        names.remove("server.stderr")
    if behavior == "missing_contradiction":  # present, yet also reported missing
        missing = ["server.stderr"]
    manifest = [{"path": n, "size_bytes": len(files[n]),
                 "sha256": hashlib.sha256(files[n]).hexdigest()} for n in names]
    wire = {"files": {n: base64.b64encode(files[n]).decode() for n in names},
            "manifest": {"files": manifest}, "missing_files": missing}
    if behavior == "bad_base64":
        wire["files"]["server.jsonl"] = "!!!not-base64!!!"
    if behavior == "bad_digest":
        wire["manifest"]["files"][1]["sha256"] = "0" * 64
    if behavior == "bad_size":
        wire["manifest"]["files"][1]["size_bytes"] += 1
    if behavior == "unknown_name":
        wire["files"]["extra.txt"] = base64.b64encode(b"x").decode()
        wire["manifest"]["files"].append({"path": "extra.txt", "size_bytes": 1,
                                          "sha256": hashlib.sha256(b"x").hexdigest()})
    if behavior == "traversal":
        wire["files"]["../escape.txt"] = base64.b64encode(b"x").decode()
        wire["manifest"]["files"].append({"path": "../escape.txt", "size_bytes": 1,
                                          "sha256": hashlib.sha256(b"x").hexdigest()})
    if behavior == "flood":
        flood()
    if behavior == "invalid":
        print("{not json")
    else:
        print(json.dumps(wire))
    sys.exit(5 if behavior == "nonzero" else 0)
"""


def lifecycle() -> ModuleType:
    """The module under test, imported as the contract names it. Never skipped."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return importlib.import_module("scripts.receiver_lifecycle")


class Harness:
    """Fake session/stop/cleanup/capture commands sharing one work directory."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.work = root / "work"
        self.work.mkdir(parents=True)
        self.fake = root / "fake_remote.py"
        self.fake.write_text(FAKE)
        self.output = root / "evidence" / "receiver-lifecycle"
        monkeypatch.setenv("LC_OUTPUT", str(self.output))
        monkeypatch.setenv(
            "LC_CONTENT", json.dumps({k: base64.b64encode(v).decode() for k, v in CONTENT.items()})
        )
        self.spawned: list[int] = []

    def argv(self, role: str, behavior: str = "ok") -> list[str]:
        return [sys.executable, str(self.fake), role, behavior, str(self.work)]

    def start(self, behavior: str = "normal"):
        session = lifecycle().start_session(self.argv("session", behavior))
        self.wait_for_file("session.pid")
        # The fake writes session.pid before spawning its grandchild: wait for both, or a
        # slow runner reads the grandchild's PID file before it exists (CI 37178638100).
        self.wait_for_file("session.grandchild.pid")
        self.spawned.append(self.pid("session.pid"))
        self.spawned.append(self.pid("session.grandchild.pid"))
        return session

    def finish(self, session, *, stop="ok", cleanup="ok", capture="ok", **kwargs):
        kwargs.setdefault("shutdown_timeout", 1.0)
        kwargs.setdefault("command_timeout", 5.0)
        kwargs.setdefault("terminate_grace", 0.5)
        kwargs.setdefault("output", self.output)
        return lifecycle().finish_session(
            session,
            stop_argv=self.argv("stop", stop),
            cleanup_argv=self.argv("cleanup", cleanup),
            capture_argv=self.argv("capture", capture),
            **kwargs,
        )

    def steps(self) -> list[str]:
        path = self.work / "steps.log"
        return path.read_text().split() if path.exists() else []

    def wait_for_file(self, name: str, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.work / name).exists() and (self.work / name).read_text():
                return
            time.sleep(0.01)
        raise AssertionError(f"fake did not write {name}")

    def pid(self, name: str) -> int:
        return int((self.work / name).read_text())

    def cleanup_processes(self) -> None:
        pids = [p for p in self.work.glob("*.pid") if p.read_text()]
        for pid in self.spawned + [self.pid(p.name) for p in pids]:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def running(pid: int) -> bool:
    """True if the PID exists and is not a zombie."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def exists(pid: int) -> bool:
    """True if any process-table entry exists, zombies included (i.e. not reaped)."""
    return Path(f"/proc/{pid}").exists()


def eventually(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    h = Harness(tmp_path, monkeypatch)
    yield h
    h.cleanup_processes()
