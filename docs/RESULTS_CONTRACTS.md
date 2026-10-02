# Saved-run results report — implementation contract

Owner requested a results tool and final LinkedIn draft on 2026-10-02. This scope adds
an offline, explicit export from saved runs. It does not implement collectors, live traffic,
faults, statistical campaigns or automatic diagnosis. The existing GUI remains read-only.

## Interfaces and CLI

`diaglab.results.build_results(paths: Sequence[Path]) -> dict` loads each path once using
the existing snapshot inspector. Accept 1–32 explicitly supplied directories; reject
duplicate normalized paths and repeated verified run IDs. Input order sets anonymous
labels `Run 1`, `Run 2`, etc. No recursive scan. Inspections are processed sequentially.

`diaglab.results.render_html(report: dict) -> str` renders the report without network
resources, scripts, raw HTML from inputs, external fonts, or raw artifact embedding.

`diaglab.results.export_results(paths: Sequence[Path], output: Path) -> Path` writes
`summary.json`, `report.html`, and `checksums.json` in an absent/empty directory with the
existing secure ArtifactStore (0600 files, no-follow opens, fsync, exclusive lock).
The output cannot equal, contain, or lie inside any input directory. Reject such paths
before creating anything. Never overwrite files or mutate source evidence. A write failure
may preserve a partial output; absence of final checksums means it is not a completed bundle.

CLI: `diaglab results --run DIR [--run DIR ...] --output DIR`.
Exit 0 means the report bundle was written, even when it documents invalid/planned/failed
inputs. Those cases appear as rows with unavailable metrics. Exit 1: argument count,
duplicate or unsafe/nonempty output refusal. Exit 2: argparse usage. Exit 3: unexpected
or artifact-output failure. Missing input directories are reported with INPUT_MISSING
and no numeric values, not silently dropped. The CLI JSON announces `report`, `run_count`
and `performance_claims_accepted: false`.

## JSON summary version 1.0

Root keys: `schema_version`, `report_kind` (`saved_run_results`), `status` (`draft`),
`performance_claims_accepted` (always false), `runs` (list), `limitations` (list of strings).
Each row has `label`, `integrity`, `state`, `evidence_kind`, `run_role`, `eligibility`,
`result_verified`, `issue_codes`, `quality_flags`, `metrics`, `unavailable_reason`,
`source_digests`, and `goodput_evidence`.

`metrics` keys: `receiver_goodput_bps`, `receiver_bytes`, `receiver_duration_s`,
`sender_retransmits`, `endpoint_byte_residual`; values are numbers or null.
Only verified snapshots with verified traffic results and actual receiver intervals
expose numbers. Other rows have all-null metrics and an explicit unavailability reason.
Copy parser values; do not recompute goodput, round JSON numbers, sum streams twice, pool
runs, infer packet loss from byte residuals, or replace missing values with zero.
Zero measured goodput is numeric zero. Preserve all parser quality flags.

`goodput_evidence` copies core-resolved EvidenceReference dictionaries for goodput when
metrics are available; it may be empty if resolution was unavailable. `source_digests`
lists flat artifact name, captured byte size and SHA-256 from the snapshot, including the
manifest. Digests identify the source snapshot, not authenticate its origin. No re-read.

No paths, run/campaign IDs, hostnames/IPs/ports, commands, stderr, events, free-form failure
strings or raw JSON are exported. All displayed values are from the specified closed
fields; HTML escapes strings. Retain synthetic/pilot/measured labels and run roles; do not
upgrade eligibility or call a pilot/fixture a benchmark. Unknown unverified metadata is null.
This minimized report still requires human review before publication.

## Independent review assignments

Accepted Claude resolutions RR-1–8: unverified state, evidence kind, role, eligibility
and result_verified are null, with empty quality flags. Unavailable reasons are uppercase
codes of 2–64 characters; unverified rows use an inspection issue code. A reason is null
exactly when goodput is numeric. HTML uses the shared presentation formatter. Duplicate
paths are normalized with abspath; symlinked outputs are refused. No CLI inputs exits
1 or 2. Source digests contain exactly captured name/size/hash triples, including the
manifest; all five metric keys are always present. Evidence input tuples serialize as
JSON arrays. Report checksums cover only report.html and summary.json, using path,
size_bytes and sha256 entries with schema_version 1.0; the traffic-run checksum schema
does not apply to this separate bundle. A nonempty output is refused before locking it.

Claude owns contract-first tests and code review (proposed IDs RT-01–08): value/source
parity, unavailable/zero distinction, invalid/missing/failed inputs, evidence classes,
no source mutation, output safety/duplicates/bounds, escaping/privacy, CLI and checksums.
Do not modify existing tests while another session is working on them.
Gemini owns independent methodology/HTML/LinkedIn-claim review; routes tests to Claude.
Both update their existing canonical review files, latest scoped verdict first.
Codex owns implementation and fixes. No replacement reviewer sessions will be launched.
