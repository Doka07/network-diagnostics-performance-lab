"""Pure, finite iperf3 parsing; direction follows field paths, never sender flags."""

import ipaddress
import math
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

from diaglab.exceptions import ArtifactIntegrityError, NonfiniteValueError, TrafficExecutionError
from diaglab.serialization import parse_json

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


class Direction(StrEnum):
    SENT = "sent"
    RECEIVED = "received"


class Source(StrEnum):
    CLIENT = "client"
    EMBEDDED_SERVER = "embedded_server"
    INDEPENDENT_SERVER = "independent_server"


@dataclass(frozen=True)
class EndpointTotal:
    bytes_count: int
    start_s: float
    end_s: float
    duration_s: float
    computed_bps: float
    reported_bps: float | None
    reported_seconds: float | None
    source: Source
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlowSummary:
    socket_id: int
    local_host: str
    remote_host: str
    local_port: int
    remote_port: int
    sender: EndpointTotal | None
    receiver: EndpointTotal | None
    retransmits: int | None
    mean_rtt_us: float | None
    min_rtt_us: float | None
    max_rtt_us: float | None
    rtt_unavailability_reason: str | None


@dataclass(frozen=True)
class TrafficInterval:
    start_s: float
    end_s: float
    duration_s: float
    socket_id: int | None
    direction: Direction
    bytes_count: int
    computed_bps: float
    reported_bps: float | None
    omitted: bool
    rtt_us: float | None
    rttvar_us: float | None
    source: Source


@dataclass(frozen=True)
class Iperf3Report:
    sender: EndpointTotal
    receiver: EndpointTotal
    flows: tuple[FlowSummary, ...]
    intervals: tuple[TrafficInterval, ...]
    sender_retransmits: int | None
    endpoint_byte_residual: int
    quality_flags: tuple[str, ...]
    receiver_source: Source

    def to_dict(self) -> dict[str, Any]:
        def plain(value: Any) -> Any:
            if isinstance(value, StrEnum):
                return value.value
            if isinstance(value, dict):
                return {key: plain(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [plain(item) for item in value]
            return value

        return plain(asdict(self))


def _failure(reason: str, message: str) -> TrafficExecutionError:
    return TrafficExecutionError(message, reason_code=reason)


def _number(value: Any, name: str, *, nonnegative: bool = True) -> float:
    if type(value) not in (int, float):
        raise ArtifactIntegrityError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ArtifactIntegrityError(f"{name} exceeds finite range") from exc
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ArtifactIntegrityError(f"{name} must be finite and nonnegative")
    return result


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ArtifactIntegrityError(f"{name} must be a nonnegative integer")
    return value


def goodput_bps(bytes_count: int, duration_s: float) -> float:
    _integer(bytes_count, "bytes")
    duration = _number(duration_s, "duration")
    if duration <= 0:
        raise ArtifactIntegrityError("duration must be positive")
    try:
        rate = bytes_count * 8 / duration
    except OverflowError as exc:
        raise ArtifactIntegrityError("goodput exceeds finite range") from exc
    if not math.isfinite(rate):
        raise ArtifactIntegrityError("goodput exceeds finite range")
    return rate


def rate_matches(reported_bps: float, computed_bps: float) -> bool:
    reported = _number(reported_bps, "reported rate")
    computed = _number(computed_bps, "computed rate")
    return abs(reported - computed) <= max(1.0, 1e-6 * abs(computed))


def _time_matches(first: float, second: float) -> bool:
    return abs(first - second) <= max(1e-6, 1e-6 * abs(second))


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", f"missing or invalid {name}")
    return value


def _array(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", f"missing or invalid {name}")
    return value


def _document(text: str) -> dict:
    if type(text) is not str:
        raise _failure("TRAFFIC_OUTPUT_INVALID_JSON", "iperf3 output must be UTF-8 JSON text")
    try:
        if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise _failure("OUTPUT_LIMIT_EXCEEDED", "iperf3 JSON exceeds 16 MiB")
        result = parse_json(text)
    except UnicodeError as exc:
        raise _failure("TRAFFIC_OUTPUT_INVALID_JSON", "invalid Unicode in iperf3 JSON") from exc
    except NonfiniteValueError:
        raise
    except ArtifactIntegrityError as exc:
        raise _failure("TRAFFIC_OUTPUT_INVALID_JSON", str(exc)) from exc
    return _checked_document(result)


def _checked_document(value: Any) -> dict:
    record = _object(value, "iperf3 document")
    if "error" in record:
        message = str(record["error"])
        lowered = message.lower()
        reason = "IPERF_REPORTED_ERROR"
        if "timed out" in lowered or "timeout" in lowered:
            reason = "CONNECTION_TIMED_OUT" if "connect" in lowered else reason
        elif "refused" in lowered and "connect" in lowered:
            reason = "CONNECTION_REFUSED"
        raise _failure(reason, message)
    return record


def _metadata(document: dict, expected: int, omit: float) -> dict[int, dict]:
    start = _object(document.get("start"), "start")
    test = _object(start.get("test_start"), "start.test_start")
    if (
        test.get("protocol") != "TCP"
        or type(test.get("num_streams")) is not int
        or test["num_streams"] != expected
        or type(test.get("reverse")) not in (int, bool)
        or test["reverse"] not in (0, False)
        or type(test.get("bidir", 0)) not in (int, bool)
        or test.get("bidir", 0) not in (0, False)
    ):
        raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "expected forward TCP with configured streams")
    if "omit" not in test or not _time_matches(_number(test["omit"], "omit"), omit):
        raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "OMIT_METADATA_MISMATCH")
    connected = _array(start.get("connected"), "start.connected")
    if len(connected) != expected:
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "unexpected connected flow count")
    sockets = {}
    tuples = set()
    for item in connected:
        item = _object(item, "connected flow")
        socket_id = _integer(item.get("socket"), "socket")
        for key in ("local_host", "remote_host"):
            if type(item.get(key)) is not str:
                raise _failure(
                    "TRAFFIC_OUTPUT_UNSUPPORTED", "expected literal IPv4 socket addresses"
                )
            try:
                ipaddress.IPv4Address(item.get(key))
            except (ValueError, TypeError, ipaddress.AddressValueError) as exc:
                raise _failure(
                    "TRAFFIC_OUTPUT_UNSUPPORTED", "expected IPv4 socket identities"
                ) from exc
        for key in ("local_port", "remote_port"):
            port = _integer(item.get(key), key)
            if not 1 <= port <= 65535:
                raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "invalid socket port")
        identity = tuple(
            item[key] for key in ("local_host", "local_port", "remote_host", "remote_port")
        )
        if socket_id in sockets or identity in tuples:
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "duplicate flow identity")
        tuples.add(identity)
        sockets[socket_id] = item
    return sockets


def _total(record: Any, source: Source, direction: Direction) -> EndpointTotal:
    record = _object(record, "endpoint total")
    if any(key not in record for key in ("start", "end", "bytes")):
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "endpoint lacks start/end/bytes")
    start = _number(record["start"], "start", nonnegative=False)
    end = _number(record["end"], "end", nonnegative=False)
    duration = end - start
    count = _integer(record["bytes"], "bytes")
    computed = goodput_bps(count, duration)
    reported = (
        None if "bits_per_second" not in record else _number(record["bits_per_second"], "rate")
    )
    seconds = None if "seconds" not in record else _number(record["seconds"], "seconds")
    flags = []
    if reported is None:
        flags.append("REPORTED_RATE_UNAVAILABLE")
    elif not rate_matches(reported, computed):
        flags.append("REPORTED_RATE_MISMATCH")
    if seconds is None:
        flags.append("REPORTED_DURATION_UNAVAILABLE")
    elif not _time_matches(seconds, duration):
        flags.append("REPORTED_DURATION_MISMATCH")
    if "sender" in record and (
        type(record["sender"]) is not bool or record["sender"] != (direction == Direction.SENT)
    ):
        flags.append("SENDER_FLAG_MISMATCH")
    return EndpointTotal(
        count, start, end, duration, computed, reported, seconds, source, tuple(flags)
    )


def _same_window(first: EndpointTotal, second: EndpointTotal) -> bool:
    return _time_matches(first.start_s, second.start_s) and _time_matches(first.end_s, second.end_s)


def _flow_totals(document: dict, sockets: dict, source: Source, direction: Direction) -> dict:
    key = "sender" if direction == Direction.SENT else "receiver"
    records = _array(_object(document.get("end"), "end").get("streams"), "end.streams")
    totals = {}
    for item in records:
        record = _object(_object(item, "end flow").get(key), f"flow.{key}")
        socket_id = _integer(record.get("socket"), "socket")
        if socket_id not in sockets or socket_id in totals:
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "unknown or duplicate summary socket")
        totals[socket_id] = (_total(record, source, direction), record)
    if set(totals) != set(sockets):
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "missing expected flow summaries")
    return totals


def _aggregate(document: dict, totals: dict, source: Source, direction: Direction) -> EndpointTotal:
    key = "sum_sent" if direction == Direction.SENT else "sum_received"
    end = _object(document.get("end"), "end")
    flows = [value[0] for value in totals.values()]
    first = flows[0]
    if not all(_same_window(first, item) for item in flows):
        raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "WINDOW_MISMATCH")
    count = sum(item.bytes_count for item in flows)
    if key in end:
        result = _total(end[key], source, direction)
        if result.bytes_count != count or not _same_window(result, first):
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "aggregate disagrees with flow totals")
        return result
    return EndpointTotal(
        count,
        first.start_s,
        first.end_s,
        first.duration_s,
        goodput_bps(count, first.duration_s),
        None,
        None,
        source,
        ("AGGREGATE_DERIVED_FROM_FLOWS",),
    )


def _intervals(
    document: dict,
    sockets: dict,
    source: Source,
    direction: Direction,
    omit: float,
    flags: list[str],
) -> list[TrafficInterval]:
    results = []
    last = {}
    omitted_seen = False
    for epoch in _array(document.get("intervals"), "intervals"):
        epoch = _object(epoch, "interval")
        records = _array(epoch.get("streams"), "interval.streams")
        mapped = {}
        for raw in records:
            raw = _object(raw, "interval flow")
            socket_id = _integer(raw.get("socket"), "socket")
            if socket_id not in sockets or socket_id in mapped:
                raise _failure(
                    "TRAFFIC_OUTPUT_INCONSISTENT", "unknown or duplicate interval socket"
                )
            mapped[socket_id] = raw
        if set(mapped) != set(sockets):
            raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "missing interval flows")
        flow_values = []
        for socket_id, raw in mapped.items():
            if type(raw.get("omitted")) is not bool:
                raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "OMIT_METADATA_MISMATCH")
            flow_values.append((socket_id, raw, _total(raw, source, direction)))
        first = flow_values[0][2]
        if not all(_same_window(first, item[2]) for item in flow_values):
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "WINDOW_MISMATCH in parallel intervals")
        if len({item[1]["omitted"] for item in flow_values}) != 1:
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "OMIT_METADATA_MISMATCH")
        aggregate = epoch.get("sum")
        if aggregate is None:
            aggregate = {
                "start": first.start_s,
                "end": first.end_s,
                "bytes": sum(item[2].bytes_count for item in flow_values),
                "omitted": flow_values[0][1]["omitted"],
            }
        aggregate = _object(aggregate, "interval sum")
        if aggregate.get("omitted") != flow_values[0][1]["omitted"]:
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "OMIT_METADATA_MISMATCH")
        total = _total(aggregate, source, direction)
        if total.bytes_count != sum(
            item[2].bytes_count for item in flow_values
        ) or not _same_window(total, first):
            raise _failure(
                "TRAFFIC_OUTPUT_INCONSISTENT", "interval aggregate double-count/inconsistency"
            )
        flow_values.append((None, aggregate, total))
        for socket_id, raw, value in flow_values:
            omitted = raw.get("omitted")
            if type(omitted) is not bool or (omit == 0 and omitted):
                raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "OMIT_METADATA_MISMATCH")
            omitted_seen |= omitted
            # Omitted pre-test windows may reset the clock before the retained series.
            series = (socket_id, omitted)
            if series in last:
                previous = last[series]
                if value.start_s < previous and not _time_matches(value.start_s, previous):
                    raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "overlapping interval series")
                if value.start_s > previous and not _time_matches(value.start_s, previous):
                    flags.append("INTERVAL_GAP")
            last[series] = value.end_s
            flags.extend(value.quality_flags)
            results.append(
                TrafficInterval(
                    value.start_s,
                    value.end_s,
                    value.duration_s,
                    socket_id,
                    direction,
                    value.bytes_count,
                    value.computed_bps,
                    value.reported_bps,
                    omitted,
                    _optional_number(raw, "rtt"),
                    _optional_number(raw, "rttvar"),
                    source,
                )
            )
    if not results:
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "empty intervals")
    if not any(not item.omitted for item in results):
        raise _failure("TRAFFIC_OUTPUT_INCOMPLETE", "no retained transfer intervals")
    if omit > 0 and not omitted_seen:
        raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "OMIT_METADATA_MISMATCH: no omitted intervals")
    return results


def _optional_number(record: dict, key: str) -> float | None:
    return None if key not in record else _number(record[key], key)


def _compare(first: EndpointTotal, second: EndpointTotal) -> bool:
    return (
        first.bytes_count == second.bytes_count
        and _same_window(first, second)
        and rate_matches(first.computed_bps, second.computed_bps)
    )


def parse_iperf3(
    client_json: str, *, expected_streams: int, omit_s: float = 0.0, server_json: str | None = None
) -> Iperf3Report:
    if type(expected_streams) is not int or expected_streams not in (1, 4):
        raise _failure("TRAFFIC_OUTPUT_UNSUPPORTED", "expected_streams must be 1 or 4")
    omit = _number(omit_s, "omit_s")
    client = _document(client_json)
    sockets = _metadata(client, expected_streams, omit)
    sent = _flow_totals(client, sockets, Source.CLIENT, Direction.SENT)
    received = _flow_totals(client, sockets, Source.CLIENT, Direction.RECEIVED)
    sender = _aggregate(client, sent, Source.CLIENT, Direction.SENT)
    receiver = _aggregate(client, received, Source.CLIENT, Direction.RECEIVED)
    flags = list(sender.quality_flags + receiver.quality_flags)
    # Preserve the real client's per-flow redundancy anomaly even if server totals win.
    for total, _ in received.values():
        flags.extend(total.quality_flags)
    intervals = _intervals(client, sockets, Source.CLIENT, Direction.SENT, omit, flags)
    candidates = []
    if "server_output_json" in client:
        candidates.append((Source.EMBEDDED_SERVER, _checked_document(client["server_output_json"])))
    if server_json is not None:
        candidates.append((Source.INDEPENDENT_SERVER, _document(server_json)))
    client_identities = {
        tuple(
            row[key] for key in ("remote_host", "remote_port", "local_host", "local_port")
        ): socket_id
        for socket_id, row in sockets.items()
    }
    for source, document in candidates:
        server_sockets = _metadata(document, expected_streams, omit)
        server_totals = _flow_totals(document, server_sockets, source, Direction.RECEIVED)
        chosen = _aggregate(document, server_totals, source, Direction.RECEIVED)
        mapped = {}
        for server_id, row in server_sockets.items():
            identity = tuple(
                row[key] for key in ("local_host", "local_port", "remote_host", "remote_port")
            )
            if identity not in client_identities:
                raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "server socket identity mismatch")
            mapped[client_identities[identity]] = server_totals[server_id]
        if not _compare(receiver, chosen) or any(
            not _compare(received[key][0], mapped[key][0]) for key in received
        ):
            flags.append("RECEIVER_SOURCE_MISMATCH")
        received = mapped
        receiver = chosen
        flags.extend(chosen.quality_flags)
    if candidates:
        source, document = candidates[-1]
        receiver_intervals = _intervals(
            document,
            _metadata(document, expected_streams, omit),
            source,
            Direction.RECEIVED,
            omit,
            flags,
        )
        server_ids = _metadata(document, expected_streams, omit)
        identity_ids = {
            key: client_identities[
                tuple(
                    row[field]
                    for field in ("local_host", "local_port", "remote_host", "remote_port")
                )
            ]
            for key, row in server_ids.items()
        }
        intervals += [
            replace(item, socket_id=identity_ids[item.socket_id])
            if item.socket_id is not None
            else item
            for item in receiver_intervals
        ]
    else:
        flags.append("SERVER_OUTPUT_UNAVAILABLE")
    flows = []
    retransmits = []
    for socket_id, row in sockets.items():
        total, raw = sent[socket_id]
        receive = received[socket_id][0]
        flags.extend(total.quality_flags + receive.quality_flags)
        count = None if "retransmits" not in raw else _integer(raw["retransmits"], "retransmits")
        retransmits.append(count)
        mean = _optional_number(raw, "mean_rtt")
        minimum = _optional_number(raw, "min_rtt")
        maximum = _optional_number(raw, "max_rtt")
        flows.append(
            FlowSummary(
                socket_id,
                row["local_host"],
                row["remote_host"],
                row["local_port"],
                row["remote_port"],
                total,
                receive,
                count,
                mean,
                minimum,
                maximum,
                "TCP_INFO_UNAVAILABLE"
                if mean is None and minimum is None and maximum is None
                else None,
            )
        )
    sender_retransmits = None if any(value is None for value in retransmits) else sum(retransmits)
    if "retransmits" in client["end"].get("sum_sent", {}):
        aggregate_retransmits = _integer(client["end"]["sum_sent"]["retransmits"], "retransmits")
        if sender_retransmits is not None and aggregate_retransmits != sender_retransmits:
            raise _failure("TRAFFIC_OUTPUT_INCONSISTENT", "aggregate retransmits mismatch")
        sender_retransmits = aggregate_retransmits
    return Iperf3Report(
        sender,
        receiver,
        tuple(flows),
        tuple(intervals),
        sender_retransmits,
        sender.bytes_count - receiver.bytes_count,
        tuple(sorted(set(flags))),
        receiver.source,
    )
