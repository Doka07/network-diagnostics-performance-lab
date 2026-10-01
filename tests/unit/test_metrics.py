"""Independent unit tests for TC-U-03.

TC-U-03: Metric Batch Serializer & Validator
- JSONL batch formatting, RFC 3339 UTC strings, monotonic integer nanoseconds.
- Timestamp ordering validation (collection_start <= monotonic_ns <= collection_end).
- Duplicate metric series rejection within a single collection epoch.
- Lossless serialization and deserialization round trips.
- Metric flattening and flat-record batch reconstruction.
- Tag whitelist enforcement for blinded AnalysisSample.
"""

import copy
from typing import Any

import pytest

from diaglab.exceptions import ArtifactIntegrityError
from diaglab.models import AnalysisSample, MetricBatch


def test_tc_u_03_valid_metric_batch_creation(valid_metric_batch_dict: dict[str, Any]) -> None:
    """TC-U-03: Create a valid MetricBatch and verify field access."""
    batch = MetricBatch.from_dict(valid_metric_batch_dict)
    data = batch.to_dict()
    assert data["schema_version"] == "1.0"
    assert data["run_id"] == "r-0123456789abcdef0123456789abcdef"
    assert data["evidence_kind"] == "synthetic"
    assert data["host_id"] == "ubuntu-controller"
    assert data["collector"] == "proc_net_dev"
    assert len(data["metrics"]) == 2
    assert data["metrics"][0]["name"] == "rx_bytes"
    assert data["metrics"][0]["value"] == 1048576


def test_tc_u_03_lossless_json_line_round_trip(valid_metric_batch_dict: dict[str, Any]) -> None:
    """TC-U-03: Verify lossless round-trip to/from JSON lines string."""
    original = MetricBatch.from_dict(valid_metric_batch_dict)
    line = original.to_json_line()
    assert line.endswith("\n")

    reconstructed = MetricBatch.from_json_line(line)
    assert reconstructed.to_dict() == original.to_dict()
    assert reconstructed.to_json_line() == line


def test_tc_u_03_flatten_and_reconstruct_round_trip(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Verify flattening into individual metric records and reconstructing."""
    batch = MetricBatch.from_dict(valid_metric_batch_dict)
    flat_records = batch.flatten()

    assert len(flat_records) == 2
    assert "metric" in flat_records[0]
    assert flat_records[0]["metric"]["name"] == "rx_bytes"
    assert flat_records[1]["metric"]["name"] == "tx_bytes"

    # Reconstruct from flat records
    reconstructed = MetricBatch.from_flat_records(flat_records)
    assert reconstructed.to_dict() == batch.to_dict()


def test_tc_u_03_reject_empty_flat_records() -> None:
    """TC-U-03: MetricBatch from empty flat records must raise ArtifactIntegrityError."""
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_flat_records([])
    assert "at least one metric" in str(exc_info.value).lower()


def test_tc_u_03_reject_mismatched_epochs_in_flat_records(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Flat records belonging to different epochs or sequences cannot be combined."""
    batch1 = MetricBatch.from_dict(valid_metric_batch_dict)
    flat1 = batch1.flatten()

    batch_data2 = copy.deepcopy(valid_metric_batch_dict)
    batch_data2["sequence"] = 2
    batch_data2["monotonic_ns"] = 2_000_000_050
    batch_data2["collection_start_monotonic_ns"] = 2_000_000_010
    batch_data2["collection_end_monotonic_ns"] = 2_000_000_100
    batch2 = MetricBatch.from_dict(batch_data2)
    flat2 = batch2.flatten()

    mixed_flat = [flat1[0], flat2[0]]
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_flat_records(mixed_flat)
    assert "different collection epochs" in str(exc_info.value).lower()


def test_tc_u_03_reject_duplicate_metric_series_in_batch(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Must reject duplicate metric series (same name, scope, tags) in one batch."""
    duplicate_metric = {
        "name": "rx_bytes",
        "value": 2048,
        "unavailability_reason": None,
        "unit": "bytes",
        "scope": "interface",
        "tags": {"interface": "enp12s0"},
    }
    valid_metric_batch_dict["metrics"].append(duplicate_metric)

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "duplicate metric series" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    ("start_ns", "mid_ns", "end_ns"),
    [
        (1000, 500, 2000),  # mid before start
        (1000, 2500, 2000),  # mid after end
        (2000, 1500, 1000),  # end before start
    ],
)
def test_tc_u_03_reject_unordered_collection_timestamps(
    valid_metric_batch_dict: dict[str, Any], start_ns: int, mid_ns: int, end_ns: int
) -> None:
    """TC-U-03: Timestamps must satisfy: collection_start <= monotonic_ns <= collection_end."""
    valid_metric_batch_dict["collection_start_monotonic_ns"] = start_ns
    valid_metric_batch_dict["monotonic_ns"] = mid_ns
    valid_metric_batch_dict["collection_end_monotonic_ns"] = end_ns

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "ordered" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "invalid_utc",
    [
        "2026-10-01 18:00:00",  # Missing T and Z
        "2026-10-01T18:00:00+00:00",  # Must be Z, not offset +00:00
        "2026-10-01T18:00:00-05:00",  # Non-UTC offset
        "not_a_timestamp",  # Random string
        "2026-02-30T18:00:00Z",  # Invalid calendar date
    ],
)
def test_tc_u_03_reject_invalid_utc_rfc3339_timestamp(
    valid_metric_batch_dict: dict[str, Any], invalid_utc: str
) -> None:
    """TC-U-03: timestamp_utc must strictly conform to RFC 3339 UTC format ending in 'Z'."""
    valid_metric_batch_dict["timestamp_utc"] = invalid_utc
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert (
        "timestamp" in str(exc_info.value).lower() or "utc-rfc3339" in str(exc_info.value).lower()
    )


def test_tc_u_03_analysis_sample_allows_standard_tags() -> None:
    """TC-U-03: AnalysisSample accepts whitelisted measurement tags."""
    sample = AnalysisSample(
        collector="proc_net_dev",
        host_id="ubuntu-controller",
        timestamp_utc="2026-10-01T18:00:00Z",
        monotonic_ns=1_000_000,
        name="rx_bytes",
        value=1024,
        unit="bytes",
        scope="interface",
        tags={"interface": "enp12s0", "direction": "egress"},
        data_quality_flags=(),
    )
    assert sample.tags["interface"] == "enp12s0"
    assert sample.tags["direction"] == "egress"


def test_tc_u_03_analysis_sample_rejects_unwhitelisted_tags() -> None:
    """TC-U-03: AnalysisSample must reject tags that leak scenario identity or ground truth."""
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        AnalysisSample(
            collector="proc_net_dev",
            host_id="ubuntu-controller",
            timestamp_utc="2026-10-01T18:00:00Z",
            monotonic_ns=1_000_000,
            name="rx_bytes",
            value=1024,
            unit="bytes",
            scope="interface",
            tags={"scenario_name": "loss_1pct"},  # Leaking scenario identity!
            data_quality_flags=(),
        )
    assert "feature scope" in str(exc_info.value).lower()


# ==============================================================================
# IMPL-B-3: Mandatory campaign_id Regressions (Run-based & Session-based)
# ==============================================================================


def test_tc_u_03_missing_campaign_id_in_run_batch_raises_error(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03 / IMPL-B-3: MetricBatch with run_id but missing campaign_id is rejected."""
    valid_metric_batch_dict.pop("campaign_id")
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "campaign_id" in str(exc_info.value)


def test_tc_u_03_session_batch_requires_campaign_id(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03 / IMPL-B-3: Session-based MetricBatch requires campaign_id."""
    valid_metric_batch_dict["run_id"] = None
    valid_metric_batch_dict["agent_session_id"] = "session-agent-001"
    valid_metric_batch_dict["campaign_id"] = "c-test-001"

    # Valid session batch succeeds
    batch = MetricBatch.from_dict(valid_metric_batch_dict)
    assert batch.to_dict()["agent_session_id"] == "session-agent-001"
    assert batch.to_dict()["run_id"] is None
    assert batch.to_dict()["campaign_id"] == "c-test-001"

    # Missing campaign_id in session batch fails
    valid_metric_batch_dict.pop("campaign_id")
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "campaign_id" in str(exc_info.value)


def test_tc_u_03_reject_batch_with_neither_run_nor_session_id(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03 / IMPL-B-3: MetricBatch with neither run_id nor agent_session_id is rejected."""
    valid_metric_batch_dict["run_id"] = None
    valid_metric_batch_dict["agent_session_id"] = None
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "run_id" in str(exc_info.value) or "agent_session_id" in str(exc_info.value)


# ==============================================================================
# Bounded Metric Tags Regressions (max 32 entries, 128-char keys, 256-char values)
# ==============================================================================


def test_tc_u_03_bounded_tags_key_length_limit(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Metric tags reject keys longer than 128 characters."""
    oversized_key = "k" * 129
    valid_metric_batch_dict["metrics"][0]["tags"][oversized_key] = "valid_val"

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "128" in str(exc_info.value) or "tags" in str(exc_info.value).lower()


def test_tc_u_03_bounded_tags_value_length_limit(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Metric tags reject string values longer than 256 characters."""
    oversized_value = "v" * 257
    valid_metric_batch_dict["metrics"][0]["tags"]["long_val"] = oversized_value

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "256" in str(exc_info.value) or "tags" in str(exc_info.value).lower()


def test_tc_u_03_bounded_tags_count_limit(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Metric tags reject tag dictionaries with more than 32 entries."""
    tags_33 = {f"k_{i}": f"v_{i}" for i in range(33)}
    valid_metric_batch_dict["metrics"][0]["tags"] = tags_33

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        MetricBatch.from_dict(valid_metric_batch_dict)
    assert "32" in str(exc_info.value) or "tags" in str(exc_info.value).lower()


def test_tc_u_03_bounded_tags_allowed_limits_and_types(
    valid_metric_batch_dict: dict[str, Any],
) -> None:
    """TC-U-03: Metric tags accept up to 32 entries with allowed scalar types."""
    # 32 entries with 128-char keys and 256-char string values, plus int/bool/null
    valid_tags: dict[str, Any] = {}
    for i in range(28):
        k = f"k_{i:02d}_" + ("x" * (128 - 7))
        v = "v" * 256
        valid_tags[k] = v
    valid_tags["int_tag"] = 42
    valid_tags["float_tag"] = 3.14
    valid_tags["bool_tag"] = True
    valid_tags["null_tag"] = None

    assert len(valid_tags) == 32
    valid_metric_batch_dict["metrics"][0]["tags"] = valid_tags

    batch = MetricBatch.from_dict(valid_metric_batch_dict)
    reconstructed_tags = batch.to_dict()["metrics"][0]["tags"]
    assert len(reconstructed_tags) == 32
    assert reconstructed_tags["int_tag"] == 42
    assert reconstructed_tags["bool_tag"] is True
    assert reconstructed_tags["null_tag"] is None
