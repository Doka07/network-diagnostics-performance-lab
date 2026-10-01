"""Independent tests for TC-U-05 and TC-U-06 against docs/PHASE2_CONTRACTS.md.

TC-U-05: diaglab.traffic.parser.parse_iperf3 -- JSON parsing, direction resolution,
receiver-source precedence, multi-stream reconciliation, RTT extraction, omit handling.

TC-U-06: diaglab.traffic.parser.goodput_bps / rate_matches -- rate arithmetic and the
redundant-field tolerance rules.

Two evidence classes are used, and they are not interchangeable:
  * captured_regression fixtures under tests/fixtures/iperf3/ -- real, checksummed,
    privacy-scrubbed captures from the Phase 0 readiness check (see provenance.json).
    These exercise real build-specific anomalies (the misleading client-side `sender`
    flag, the per-flow `seconds` vs `end-start` discrepancy) that a hand-written
    synthetic fixture would likely never reproduce.
  * synthetic documents built by _document() below, used only to exercise code paths
    (4-stream reconciliation, malformed input, numeric guards) that the single real
    capture does not cover. These are never evidence of measured performance.
"""

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from diaglab.exceptions import ArtifactIntegrityError, TrafficExecutionError
from diaglab.traffic.parser import MAX_DOCUMENT_BYTES, goodput_bps, parse_iperf3, rate_matches

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "iperf3"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ==============================================================================
# Synthetic document builder -- code-path coverage only, never measurement evidence.
# ==============================================================================


def _flow_record(
    *,
    socket_id: int,
    local_port: int,
    bytes_count: int,
    duration: float,
    rtt_us: float | None,
    retransmits: int = 0,
    start: float = 0.0,
) -> dict[str, Any]:
    end = start + duration
    record: dict[str, Any] = {
        "socket": socket_id,
        "start": start,
        "end": end,
        "seconds": duration,
        "bytes": bytes_count,
        "bits_per_second": goodput_bps(bytes_count, duration),
        "retransmits": retransmits,
        "omitted": False,
    }
    if rtt_us is not None:
        record["mean_rtt"] = rtt_us
        record["min_rtt"] = rtt_us - 50
        record["max_rtt"] = rtt_us + 50
        record["rtt"] = rtt_us
        record["rttvar"] = 5.0
    return record


def _document(
    *,
    num_streams: int = 1,
    bytes_per_stream: int = 375_000_000,
    duration: float = 30.0,
    omit: float = 0.0,
    include_rtt: bool = True,
    include_server: bool = False,
    reverse: bool = False,
) -> dict[str, Any]:
    """Build a minimal, internally-consistent synthetic iperf3 -J document."""
    sockets = list(range(5, 5 + num_streams))
    connected = [
        {
            "socket": socket_id,
            "local_host": "192.0.2.10",
            "local_port": 40000 + socket_id,
            "remote_host": "192.0.2.20",
            "remote_port": 5201,
        }
        for socket_id in sockets
    ]
    sent_flows = [
        _flow_record(
            socket_id=socket_id,
            local_port=40000 + socket_id,
            bytes_count=bytes_per_stream,
            duration=duration,
            rtt_us=1500.0 if include_rtt else None,
        )
        for socket_id in sockets
    ]
    received_flows = [
        {**copy.deepcopy(record), "bits_per_second": record["bits_per_second"]}
        for record in sent_flows
    ]
    total_bytes = bytes_per_stream * num_streams
    sum_sent = {
        "start": 0.0,
        "end": duration,
        "seconds": duration,
        "bytes": total_bytes,
        "bits_per_second": goodput_bps(total_bytes, duration),
        "retransmits": 0,
    }
    sum_received = {
        "start": 0.0,
        "end": duration,
        "seconds": duration,
        "bytes": total_bytes,
        "bits_per_second": goodput_bps(total_bytes, duration),
    }
    streams_end = [
        {"sender": sent, "receiver": received}
        for sent, received in zip(sent_flows, received_flows, strict=True)
    ]
    interval = {
        "streams": [{**flow, "omitted": False} for flow in sent_flows],
        "sum": {
            "start": 0.0,
            "end": duration,
            "bytes": total_bytes,
            "omitted": False,
        },
    }
    document: dict[str, Any] = {
        "start": {
            "connected": connected,
            "version": "iperf 3.16",
            "system_info": "synthetic test host",
            "test_start": {
                "protocol": "TCP",
                "num_streams": num_streams,
                "omit": omit,
                "duration": duration,
                "reverse": 1 if reverse else 0,
                "bidir": 0,
            },
        },
        "intervals": [interval],
        "end": {
            "streams": streams_end,
            "sum_sent": sum_sent,
            "sum_received": sum_received,
        },
    }
    if include_server:
        server = copy.deepcopy(document)
        # The server names connections from its own side: local/remote reversed.
        server["start"]["connected"] = [
            {
                "socket": item["socket"],
                "local_host": item["remote_host"],
                "local_port": item["remote_port"],
                "remote_host": item["local_host"],
                "remote_port": item["local_port"],
            }
            for item in connected
        ]
        document["server_output_json"] = server
    return document


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document)


# ==============================================================================
# TC-U-05: direction resolution, never from the sender boolean
# ==============================================================================


def test_tc_u_05_direction_resolved_by_key_path_not_boolean() -> None:
    """A record's key path (sum_sent/sum_received, sender/receiver) decides direction;
    an internally contradictory `sender` boolean is flagged, never trusted."""
    document = _document()
    document["end"]["sum_received"]["sender"] = True  # the real, observed client bug
    document["end"]["streams"][0]["receiver"]["sender"] = True
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert report.receiver.bytes_count == document["end"]["sum_received"]["bytes"]
    assert "SENDER_FLAG_MISMATCH" in report.quality_flags


def test_tc_u_05_consistent_sender_flag_raises_no_mismatch() -> None:
    document = _document()
    document["end"]["sum_sent"]["sender"] = True
    document["end"]["sum_received"]["sender"] = False
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert "SENDER_FLAG_MISMATCH" not in report.quality_flags


# ==============================================================================
# TC-U-05: receiver source precedence -- independent > embedded > client
# ==============================================================================


def test_tc_u_05_client_only_source_when_no_server_output() -> None:
    document = _document(include_server=False)
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert report.receiver_source == "client"
    assert "SERVER_OUTPUT_UNAVAILABLE" in report.quality_flags


def test_tc_u_05_embedded_server_output_wins_over_client() -> None:
    document = _document(include_server=True)
    # Corrupt the client's own receiver record consistently (aggregate and per-flow
    # agree with each other, so the client's view is internally coherent) but leave
    # the embedded server copy untouched; the embedded copy must still win.
    document["end"]["sum_received"]["bytes"] += 999
    document["end"]["streams"][0]["receiver"]["bytes"] += 999
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert report.receiver_source == "embedded_server"
    assert (
        report.receiver.bytes_count
        == document["server_output_json"]["end"]["sum_received"]["bytes"]
    )
    assert "RECEIVER_SOURCE_MISMATCH" in report.quality_flags


def test_tc_u_05_independent_server_document_wins_over_embedded() -> None:
    document = _document(include_server=True)
    independent = copy.deepcopy(document["server_output_json"])
    report = parse_iperf3(
        _dump(document), expected_streams=1, omit_s=0.0, server_json=_dump(independent)
    )
    assert report.receiver_source == "independent_server"


def test_tc_u_05_disagreeing_independent_server_flags_mismatch_but_still_wins() -> None:
    document = _document(include_server=True)
    independent = copy.deepcopy(document["server_output_json"])
    independent["end"]["sum_received"]["bytes"] += 4096
    independent["end"]["streams"][0]["receiver"]["bytes"] += 4096
    report = parse_iperf3(
        _dump(document), expected_streams=1, omit_s=0.0, server_json=_dump(independent)
    )
    assert "RECEIVER_SOURCE_MISMATCH" in report.quality_flags
    # Highest-priority source still wins even when flagged as disagreeing.
    assert report.receiver_source == "independent_server"
    assert report.receiver.bytes_count == independent["end"]["sum_received"]["bytes"]


def test_tc_u_05_malformed_independent_server_document_is_not_silently_ignored() -> None:
    document = _document(include_server=True)
    with pytest.raises((TrafficExecutionError, ArtifactIntegrityError)):
        parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0, server_json="{not json")


# ==============================================================================
# TC-U-05: real captured evidence (captured_regression; never used as measurement)
# ==============================================================================


def test_tc_u_05_captured_success_reproduces_known_real_anomalies() -> None:
    """Regression-pins the exact two anomalies found by hand in the readiness evidence."""
    client = _read_fixture("single_stream_success_client.json")
    server = _read_fixture("single_stream_success_server.json")
    report = parse_iperf3(client, expected_streams=1, omit_s=0.0, server_json=server)
    assert report.receiver_source == "independent_server"
    assert report.receiver.bytes_count == 3530686464
    assert report.sender.bytes_count == 3531997184
    assert report.endpoint_byte_residual == 3531997184 - 3530686464
    assert "SENDER_FLAG_MISMATCH" in report.quality_flags
    assert "REPORTED_DURATION_MISMATCH" in report.quality_flags
    assert "RECEIVER_SOURCE_MISMATCH" not in report.quality_flags
    assert report.flows[0].mean_rtt_us == pytest.approx(1946.0)
    assert report.sender_retransmits == 0


def test_tc_u_05_captured_success_without_independent_server_falls_back_to_embedded() -> None:
    client = _read_fixture("single_stream_success_client.json")
    report = parse_iperf3(client, expected_streams=1, omit_s=0.0)
    assert report.receiver_source == "embedded_server"
    assert report.receiver.bytes_count == 3530686464


def test_tc_u_05_captured_connection_timeout_classified_correctly() -> None:
    document = _read_fixture("connection_timeout_client.json")
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(document, expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == "CONNECTION_TIMED_OUT"
    assert "Connection timed out" in str(excinfo.value)


# ==============================================================================
# TC-U-05: top-level error mapping
# ==============================================================================


@pytest.mark.parametrize(
    ("error_text", "expected_reason"),
    [
        ("unable to connect: Connection timed out", "CONNECTION_TIMED_OUT"),
        ("unable to connect to server - Connection refused", "CONNECTION_REFUSED"),
        ("test failed for an unrelated reason", "IPERF_REPORTED_ERROR"),
    ],
)
def test_tc_u_05_error_field_classification(error_text: str, expected_reason: str) -> None:
    document = {"start": {}, "intervals": [], "end": {}, "error": error_text}
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == expected_reason


# ==============================================================================
# TC-U-05: malformed / incomplete / oversized input never raises the wrong class
# ==============================================================================


def test_tc_u_05_malformed_json_is_invalid_json_not_a_crash() -> None:
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3("{not valid json", expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_INVALID_JSON"


def test_tc_u_05_empty_document_is_incomplete_not_a_crash() -> None:
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3("{}", expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_INCOMPLETE"


def test_tc_u_05_oversized_document_is_rejected_before_decoding() -> None:
    oversized = " " * (MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(oversized, expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == "OUTPUT_LIMIT_EXCEEDED"


def test_tc_u_05_nonfinite_number_raises_artifact_integrity_error_not_traffic_error() -> None:
    """Strict numeric violations are a distinct failure class from malformed JSON."""
    document = _document()
    marker = 123456789.0
    document["end"]["sum_sent"]["bits_per_second"] = marker
    # json.dumps never emits a bare NaN literal; splice one in directly to exercise
    # the parser's own nonfinite-number rejection on realistic document shape.
    raw = _dump(document).replace(str(marker), "NaN", 1)
    with pytest.raises(ArtifactIntegrityError):
        parse_iperf3(raw, expected_streams=1, omit_s=0.0)


def test_tc_u_05_duplicate_socket_id_in_connected_is_rejected() -> None:
    document = _document(num_streams=4)
    document["start"]["connected"][1]["socket"] = document["start"]["connected"][0]["socket"]
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_INCONSISTENT"


def test_tc_u_05_missing_flow_summary_is_incomplete() -> None:
    document = _document(num_streams=4)
    document["end"]["streams"].pop()
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_INCOMPLETE"


def test_tc_u_05_wrong_stream_count_is_unsupported() -> None:
    document = _document(num_streams=1)
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_UNSUPPORTED"


def test_tc_u_05_reverse_mode_is_rejected_as_unsupported() -> None:
    document = _document(reverse=True)
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_UNSUPPORTED"


def test_tc_u_05_aggregate_disagreeing_with_flow_totals_is_inconsistent() -> None:
    document = _document(num_streams=4)
    document["end"]["sum_received"]["bytes"] += 1
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_INCONSISTENT"


def test_tc_u_05_aggregate_derived_from_flows_when_sum_absent() -> None:
    document = _document(num_streams=4)
    del document["end"]["sum_sent"]
    report = parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert "AGGREGATE_DERIVED_FROM_FLOWS" in report.sender.quality_flags
    assert report.sender.bytes_count == sum(
        flow["sender"]["bytes"] for flow in document["end"]["streams"]
    )


def test_tc_u_05_parallel_streams_never_double_counted() -> None:
    document = _document(num_streams=4, bytes_per_stream=100_000_000, duration=30.0)
    report = parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    assert report.sender.bytes_count == 400_000_000
    assert len(report.flows) == 4
    assert report.sender.computed_bps == pytest.approx(goodput_bps(400_000_000, 30.0))


# ==============================================================================
# TC-U-05: RTT extraction and availability
# ==============================================================================


def test_tc_u_05_rtt_extracted_when_present() -> None:
    document = _document(include_rtt=True)
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    flow = report.flows[0]
    assert flow.mean_rtt_us == pytest.approx(1500.0)
    assert flow.min_rtt_us == pytest.approx(1450.0)
    assert flow.max_rtt_us == pytest.approx(1550.0)
    assert flow.rtt_unavailability_reason is None


def test_tc_u_05_rtt_missing_is_none_with_reason_not_zero() -> None:
    document = _document(include_rtt=False)
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    flow = report.flows[0]
    assert flow.mean_rtt_us is None
    assert flow.min_rtt_us is None
    assert flow.max_rtt_us is None
    assert flow.rtt_unavailability_reason == "TCP_INFO_UNAVAILABLE"


# ==============================================================================
# TC-U-05: omit handling -- no arbitrary trimming, metadata must agree with config
# ==============================================================================


def test_tc_u_05_zero_omit_retains_every_observed_interval() -> None:
    document = _document(omit=0.0)
    # Two retained intervals; nothing should be trimmed away.
    document["intervals"].append(copy.deepcopy(document["intervals"][0]))
    document["intervals"][1]["streams"][0]["start"] = 30.0
    document["intervals"][1]["streams"][0]["end"] = 60.0
    document["intervals"][1]["streams"][0]["seconds"] = 30.0
    document["intervals"][1]["sum"]["start"] = 30.0
    document["intervals"][1]["sum"]["end"] = 60.0
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    sent_intervals = [item for item in report.intervals if item.direction == "sent"]
    assert len(sent_intervals) == 4  # 2 epochs x (1 flow + 1 aggregate)
    assert all(not item.omitted for item in sent_intervals)


def test_tc_u_05_omit_mismatch_with_declared_test_metadata_is_rejected() -> None:
    document = _document(omit=0.0)
    # omit_s=5 is requested, but the document's own test_start.omit still says 0.
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=1, omit_s=5.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_UNSUPPORTED"


def test_tc_u_05_omitted_interval_present_when_omit_configured() -> None:
    document = _document(omit=5.0)
    document["start"]["test_start"]["omit"] = 5.0
    warmup = copy.deepcopy(document["intervals"][0])
    for flow in warmup["streams"]:
        flow["omitted"] = True
    warmup["sum"]["omitted"] = True
    document["intervals"].insert(0, warmup)
    document["intervals"][1]["streams"][0]["start"] = 5.0
    document["intervals"][1]["streams"][0]["end"] = 35.0
    document["intervals"][1]["sum"]["start"] = 5.0
    document["intervals"][1]["sum"]["end"] = 35.0
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=5.0)
    sent = [item for item in report.intervals if item.direction == "sent"]
    assert any(item.omitted for item in sent)
    assert any(not item.omitted for item in sent)


def test_tc_u_05_omit_configured_but_no_omitted_interval_present_is_rejected() -> None:
    document = _document(omit=5.0)
    document["start"]["test_start"]["omit"] = 5.0
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse_iperf3(_dump(document), expected_streams=1, omit_s=5.0)
    assert excinfo.value.reason_code == "TRAFFIC_OUTPUT_UNSUPPORTED"


# ==============================================================================
# TC-U-06: goodput_bps / rate_matches arithmetic and tolerances
# ==============================================================================


def test_tc_u_06_goodput_bps_formula() -> None:
    assert goodput_bps(1_000_000, 8.0) == pytest.approx(1_000_000)


def test_tc_u_06_goodput_requires_positive_duration() -> None:
    with pytest.raises(ArtifactIntegrityError):
        goodput_bps(100, 0.0)
    with pytest.raises(ArtifactIntegrityError):
        goodput_bps(100, -1.0)


@pytest.mark.parametrize("bad_bytes", [-1, 1.5, True, "100"])
def test_tc_u_06_goodput_rejects_non_nonnegative_integer_bytes(bad_bytes: object) -> None:
    with pytest.raises(ArtifactIntegrityError):
        goodput_bps(bad_bytes, 1.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_duration", [math.inf, math.nan, "1", None])
def test_tc_u_06_goodput_rejects_nonfinite_or_wrong_type_duration(bad_duration: object) -> None:
    with pytest.raises(ArtifactIntegrityError):
        goodput_bps(100, bad_duration)  # type: ignore[arg-type]


def test_tc_u_06_rate_matches_within_tolerance() -> None:
    computed = goodput_bps(1_000_000_000, 8.0)
    assert rate_matches(computed, computed) is True
    assert rate_matches(computed + 1.0, computed) is True  # within max(1 bps, 1e-6*computed)
    assert rate_matches(computed + 0.5, computed) is True


def test_tc_u_06_rate_matches_rejects_beyond_tolerance() -> None:
    computed = goodput_bps(1_000_000_000, 8.0)
    tolerance = max(1.0, 1e-6 * abs(computed))
    assert rate_matches(computed + tolerance + 10.0, computed) is False


def test_tc_u_06_reported_rate_mismatch_flagged_not_raised() -> None:
    document = _document()
    document["end"]["sum_sent"]["bits_per_second"] *= 2
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert "REPORTED_RATE_MISMATCH" in report.sender.quality_flags
    # Raw reported value preserved verbatim alongside the computed one.
    assert report.sender.reported_bps == document["end"]["sum_sent"]["bits_per_second"]


def test_tc_u_06_missing_reported_rate_is_flagged_unavailable() -> None:
    document = _document()
    del document["end"]["sum_sent"]["bits_per_second"]
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert report.sender.reported_bps is None
    assert "REPORTED_RATE_UNAVAILABLE" in report.sender.quality_flags


def test_tc_u_06_reported_duration_mismatch_flagged_not_raised() -> None:
    document = _document()
    document["end"]["sum_sent"]["seconds"] += 1.0
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert "REPORTED_DURATION_MISMATCH" in report.sender.quality_flags
    assert report.sender.duration_s == pytest.approx(30.0)  # end-start is still authoritative


def test_tc_u_06_duration_is_always_end_minus_start_not_the_seconds_field() -> None:
    """Direct regression for the real anomaly: seconds must never override end-start."""
    document = _document()
    document["end"]["streams"][0]["receiver"]["seconds"] = 1.0  # deliberately wrong
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    flow = report.flows[0]
    assert flow.receiver.duration_s == pytest.approx(flow.receiver.end_s - flow.receiver.start_s)
    assert flow.receiver.duration_s != pytest.approx(1.0)
    assert "REPORTED_DURATION_MISMATCH" in flow.receiver.quality_flags


def test_tc_u_06_endpoint_byte_residual_is_signed_and_not_interpreted() -> None:
    document = _document(include_server=True)
    document["server_output_json"]["end"]["sum_received"]["bytes"] -= 2048
    for flow in document["server_output_json"]["end"]["streams"]:
        flow["receiver"]["bytes"] -= 2048
    report = parse_iperf3(_dump(document), expected_streams=1, omit_s=0.0)
    assert report.endpoint_byte_residual == 2048
    assert isinstance(report.endpoint_byte_residual, int)


def test_tc_u_06_whole_window_rate_uses_summed_bytes_over_window_not_mean_of_rates() -> None:
    document = _document(num_streams=4, bytes_per_stream=50_000_000, duration=30.0)
    report = parse_iperf3(_dump(document), expected_streams=4, omit_s=0.0)
    expected = goodput_bps(50_000_000 * 4, 30.0)
    assert report.sender.computed_bps == pytest.approx(expected)
