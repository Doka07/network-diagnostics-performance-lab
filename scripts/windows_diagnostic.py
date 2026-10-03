"""Bounded Ubuntu-to-Windows diagnostic operator using pinned SSH and durable finalization.

Run only with owner authorization. This is checkout-only tooling, not a diaglab CLI API.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from diaglab.artifacts.store import ArtifactStore  # noqa: E402
from diaglab.config import load_config  # noqa: E402
from scripts.diagnostic_finalize import finalize_diagnostic  # noqa: E402
from scripts.receiver_lifecycle import _reap, finish_session, start_session  # noqa: E402

FINGERPRINT = "SHA256:nj9ZCrPpi4JT2NcfnY+vNntUpskuKFZfwI/kDR4h50w"


def run(config_path: Path, known_hosts: Path) -> dict:
    config = load_config(config_path)
    data = config.data
    if (
        data["target"]["host"] != "10.0.0.23"
        or data["target"]["port"] != 5201
        or data["traffic"]["streams"] not in (1, 4)
        or data["traffic"]["duration_s"] != 30
        or data["safety"]["dry_run"]
        or data["scenario"]["kind"] != "baseline"
    ):
        raise ValueError("operator supports only authorized one/four-stream 30 s baseline pilots")
    token = uuid4().hex
    root = REPO / "artifacts" / ("windows-control-" + token)
    print(f"DIAGNOSTIC_ROOT={root}", flush=True)
    session = None
    lifecycle = None
    traffic = None
    failures = []
    helper = REPO / "scripts/windows_receiver.ps1"
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    options = [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
    ]
    ssh = ["ssh", *options, "Denis@10.0.0.23"]
    checks = {}
    phase = "PREFLIGHT"
    remote = None

    def command(script):
        prefix = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';\n"
        encoded = base64.b64encode((prefix + script).encode("utf-16le")).decode()
        return ssh + ["powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded]

    def action(name):
        return ssh + [
            f'powershell.exe -NoProfile -NonInteractive -File "{remote}" -Action {name} '
            f"-Token {token} -LocalAddress 10.0.0.23 -PeerAddress 10.0.0.22 "
            '-InterfaceAlias "Ethernet 4" -Port 5201'
        ]

    with ArtifactStore(root, create=True) as store:
        store.write("operator.py", Path(__file__).read_bytes())
        store.write("helper.ps1", helper.read_bytes())
        store.write("pilot.yaml", config_path.read_bytes())
        for name, source in {
            "parser.py": REPO / "diaglab/traffic/parser.py",
            "receiver_lifecycle.py": REPO / "scripts/receiver_lifecycle.py",
            "diagnostic_finalize.py": REPO / "scripts/diagnostic_finalize.py",
        }.items():
            store.write("source-" + name, source.read_bytes())
        store.write_json(
            "context.json",
            {
                "diagnostic_only": True,
                "condition": "AC sleep/hibernate disabled; SSH restarted; original probe enabled",
                "owner_authorization": "standing autonomous diagnostic approval",
                "helper_sha256": digest,
            },
        )

        def query(name, script):
            store.write(name + ".ps1", script.encode())
            try:
                result = subprocess.run(command(script), capture_output=True, timeout=70)
                store.write(name + ".stdout", result.stdout)
                store.write(name + ".stderr", result.stderr)
            except subprocess.TimeoutExpired as exc:
                store.write(name + ".stdout", exc.stdout or b"")
                store.write(name + ".stderr", exc.stderr or b"")
                raise
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            return json.loads(result.stdout.decode("utf-8-sig"))

        try:
            fingerprint = subprocess.check_output(
                ["ssh-keygen", "-lf", str(known_hosts)], text=True, timeout=10
            )
            if FINGERPRINT not in fingerprint:
                raise ValueError("unexpected host fingerprint")
            env = query("environment", "[ordered]@{temp=$env:TEMP} | ConvertTo-Json")
            remote = env["temp"].replace("\\", "/") + f"/ndpl-helper-{token}.ps1"
            if not all(c.isalnum() or c in ":/_.- " for c in remote):
                raise ValueError("unsafe staging path")
            copied = subprocess.run(
                ["scp", *options, str(helper), "Denis@10.0.0.23:" + remote],
                capture_output=True,
                timeout=60,
            )
            store.write("copy.stdout", copied.stdout)
            store.write("copy.stderr", copied.stderr)
            if copied.returncode:
                raise RuntimeError("helper deployment failed")
            validation = query(
                "helper-validation",
                f"""
$t=$null; $e=$null
$null=[System.Management.Automation.Language.Parser]::ParseFile('{remote}',[ref]$t,[ref]$e)
[ordered]@{{sha256=(Get-FileHash '{remote}' -Algorithm SHA256).Hash.ToLowerInvariant();
parse_errors=$e.Count}} | ConvertTo-Json
""",
            )
            if validation != {"sha256": digest, "parse_errors": 0}:
                raise ValueError("helper validation failed")
            phase = "READINESS"
            session = start_session(action("Start"))
            absence = f"""
Import-Module NetTCPIP
Import-Module NetSecurity
$o=Get-Content (Join-Path $env:TEMP 'ndpl-receiver-{token}/owner.json') -Raw | ConvertFrom-Json
$p=Get-Process -Id $o.pid -ErrorAction SilentlyContinue
$s=[ordered]@{{process_gone=($null -eq $p);
listener_gone=(@(Get-NetTCPConnection -LocalPort 5201 -State Listen `
-ErrorAction SilentlyContinue).Count -eq 0);
rule_gone=!(Get-NetFirewallRule -Name 'DiagLab-Receiver-{token}' -ErrorAction SilentlyContinue)}}
$s | ConvertTo-Json
if ($s.Values -contains $false) {{ exit 3 }}
"""
            checks["absence"] = command(absence)
            identity = query(
                "identity-ready",
                f"""
Import-Module NetTCPIP
$d=Join-Path $env:TEMP 'ndpl-receiver-{token}'
$deadline=(Get-Date).AddSeconds(45)
while (!(Test-Path "$d/ready") -and (Get-Date) -lt $deadline) {{ Start-Sleep -Milliseconds 500 }}
if (!(Test-Path "$d/ready")) {{ throw 'Readiness deadline exceeded' }}
$o=Get-Content "$d/owner.json" -Raw | ConvertFrom-Json
$p=Get-Process -Id $o.pid
[ordered]@{{identity_match=([string]$p.StartTime.ToUniversalTime().Ticks -eq $o.start_ticks `
-and $p.Path -eq $o.executable);
helper_sha256=$o.helper_sha256;
owned_listener=(@(Get-NetTCPConnection -State Listen -LocalPort 5201 |
Where-Object {{ $_.OwningProcess -eq $p.Id -and $_.LocalAddress -eq '10.0.0.23' }}
).Count -eq 1)}} | ConvertTo-Json
""",
            )
            if not (
                identity["identity_match"]
                and identity["owned_listener"]
                and identity["helper_sha256"] == digest
            ):
                raise ValueError("receiver identity mismatch")
            phase = "TRAFFIC"
            print(
                f"READY; running one 30-second {data['traffic']['streams']}-stream control",
                flush=True,
            )
            run_root = root / "run-1"
            cli = [str(REPO / ".venv/bin/diaglab")]
            checks["verify"] = cli + ["verify", "--run", str(run_root)]
            checks["export"] = cli + [
                "results",
                "--run",
                str(run_root),
                "--output",
                str(root / "report"),
            ]
            child = start_session(
                cli
                + [
                    "run",
                    "--config",
                    str(root / "pilot.yaml"),
                    "--output",
                    str(run_root),
                    "--execute",
                ]
            )
            try:
                child.process.wait(timeout=65)
            finally:
                _reap(child, 2)
                store.write("traffic.stdout", bytes(child.buffers["stdout"]))
                store.write("traffic.stderr", bytes(child.buffers["stderr"]))
                path = run_root / "command.json"
                if path.exists():
                    outcome = json.loads(path.read_text())
                    traffic = {
                        "started": any(
                            event.get("name") == "TRAFFIC_STARTED"
                            for event in json.loads((run_root / "manifest.json").read_text())[
                                "events"
                            ]
                        ),
                        "failure": outcome.get("failure_reason"),
                    }
                    if not traffic["started"]:
                        if traffic["failure"]:
                            failures.append("RUN_PREFLIGHT_FAILED")
                        traffic = None
                if child.process.returncode != 0:
                    failures.append("RUN_COMMAND_NONZERO")
            print("TRAFFIC_RETURN=" + str(child.process.returncode), flush=True)
        except (Exception, KeyboardInterrupt) as exc:
            failures.append(
                phase + ("_TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "_FAILED")
            )
            store.write("operator-exception.txt", (type(exc).__name__ + ": " + str(exc)).encode())
        finally:
            try:
                if session is not None:
                    lifecycle = finish_session(
                        session,
                        stop_argv=action("Stop"),
                        cleanup_argv=action("Cleanup"),
                        capture_argv=action("Capture"),
                        output=root / "lifecycle",
                        traffic_failure=traffic["failure"] if traffic else None,
                    )
            finally:
                # Release the temporary creation lock before hashing the full tree.
                store.close()
                record = finalize_diagnostic(
                    root,
                    traffic=traffic,
                    operator_failures=failures,
                    lifecycle=lifecycle,
                    checks=checks,
                )
                print("FINAL=" + json.dumps(record), flush=True)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config, args.known_hosts)
    raise SystemExit(0 if result["diagnostic_complete"] and not result["traffic_failure"] else 3)
