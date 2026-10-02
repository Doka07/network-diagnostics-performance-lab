"""TG-11 threading/cancellation and TG-12 offscreen smoke tests for diaglab.gui (GC-8, GC-9,
R-18, R-20). Written from docs/GUI_CONTRACTS.md before implementation.

Without PySide6 this module is skipped visibly (pytest -ra lists it). The dedicated GUI
CI jobs must set NDPL_REQUIRE_GUI=1, which turns a missing Qt into a failure instead.
"""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

if os.environ.get("NDPL_REQUIRE_GUI") == "1":
    QtCore = importlib.import_module("PySide6.QtCore")
else:
    QtCore = pytest.importorskip("PySide6.QtCore", reason="gui extra not installed")
QtGui = importlib.import_module("PySide6.QtGui")
QtTest = importlib.import_module("PySide6.QtTest")
QtWidgets = importlib.import_module("PySide6.QtWidgets")

from .runs import clone, edit_json, rehash  # noqa: E402

LOAD_TIMEOUT_S = 60.0
CANCEL_BOUND_S = 2.0
HEARTBEAT_MS = 20
MAX_GAP_S = 0.250


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    instance = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield instance


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    for name in ("home", "config", "data", "cache", "state"):
        (home / name).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    return home


@pytest.fixture
def window(app, isolated_home):
    gui = importlib.import_module("diaglab.gui")
    instance = gui.MainWindow()
    instance.show()
    yield instance
    if instance.is_loading():
        instance.cancel_load()
        wait_until(lambda: not instance.is_loading(), LOAD_TIMEOUT_S)
    instance.close()
    wait_until(lambda: not instance.isVisible(), LOAD_TIMEOUT_S)


def wait_until(predicate, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        QtTest.QTest.qWait(10)
    return predicate()


def visible_texts(widget) -> list[str]:
    texts = []
    for child in widget.findChildren(QtWidgets.QLabel):
        texts.append(child.text())
    for child in widget.findChildren(QtWidgets.QAbstractButton):
        texts.append(child.text())
    if isinstance(widget, QtWidgets.QMainWindow) and widget.statusBar() is not None:
        texts.append(widget.statusBar().currentMessage())
        texts.extend(label.text() for label in widget.statusBar().findChildren(QtWidgets.QLabel))
    return texts


def open_and_wait(window, path: Path):
    window.open_run(path)
    assert wait_until(lambda: not window.is_loading(), LOAD_TIMEOUT_S), "load never finished"
    return window.current_view


def files_under(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def open_descriptors() -> set[str]:
    return set(os.listdir("/proc/self/fd")) if Path("/proc/self/fd").exists() else set()


# ----------------------------------------------------------------------- TG-12 smoke


@pytest.mark.parametrize(
    ("name", "integrity_word"),
    [
        ("captured_success", "Verified snapshot"),
        ("connection_timeout", "Verified snapshot"),
        ("interrupted", "Verified snapshot"),
        ("no_server", "Verified snapshot"),
    ],
)
def test_tg12_window_shows_three_separate_text_statuses(
    window, fresh, name, integrity_word
) -> None:
    run_view = open_and_wait(window, fresh(name))
    assert run_view is not None
    assert integrity_word in run_view.integrity_text
    texts = visible_texts(window)
    for status in (run_view.integrity_text, run_view.traffic_text, run_view.eligibility_text):
        assert any(status in text for text in texts), (status, texts)


def test_tg12_tampered_run_opens_and_reports_integrity_failure(window, fresh) -> None:
    run = fresh("captured_success")
    with (run / "client.stderr").open("ab") as handle:
        handle.write(b"x")
    run_view = open_and_wait(window, run)
    assert "Integrity failed" in run_view.integrity_text
    assert any("Integrity failed" in text for text in visible_texts(window))


def test_tg12_open_shortcut_and_no_live_controls(window) -> None:
    actions = window.findChildren(QtGui.QAction)
    open_keys = QtGui.QKeySequence("Ctrl+O")
    assert any(open_keys in action.shortcuts() for action in actions)
    live_words = ("start", "stop", "execute", "plan experiment", "run traffic")
    controls = [(a.text(), a.isEnabled()) for a in actions]
    controls += [(b.text(), b.isEnabled()) for b in window.findChildren(QtWidgets.QAbstractButton)]
    enabled_live = [
        text
        for text, enabled in controls
        if enabled and any(word in text.casefold() for word in live_words)
    ]
    assert enabled_live == []


def test_tg12_focus_order_open_then_filter_then_views(window) -> None:
    chain = []
    widget = window.nextInFocusChain()
    for _ in range(500):
        if widget is window or widget in chain:
            break
        if widget.focusPolicy() & QtCore.Qt.FocusPolicy.TabFocus and widget.isVisibleTo(window):
            chain.append(widget)
        widget = widget.nextInFocusChain()

    def first(predicate) -> int:
        for index, item in enumerate(chain):
            if predicate(item):
                return index
        pytest.fail(f"focus chain lacks a required widget: {[type(w).__name__ for w in chain]}")

    open_index = first(
        lambda w: isinstance(w, QtWidgets.QAbstractButton) and "open" in w.text().casefold()
    )
    filter_index = first(lambda w: isinstance(w, QtWidgets.QLineEdit))
    view_index = first(lambda w: isinstance(w, QtWidgets.QAbstractItemView))
    assert open_index < filter_index < view_index


def test_tg12_themes_are_in_memory_only(window, fresh, isolated_home) -> None:
    open_and_wait(window, fresh("captured_success"))
    window.set_theme("light")
    light = window.palette().color(QtGui.QPalette.ColorRole.Window).lightness()
    window.set_theme("dark")
    dark = window.palette().color(QtGui.QPalette.ColorRole.Window).lightness()
    assert dark < light
    with pytest.raises(ValueError):
        window.set_theme("solarized")
    QtTest.QTest.qWait(50)
    assert files_under(isolated_home) == []


# ------------------------------------------------------- TG-11 responsiveness/cancel


def test_tg11_ui_thread_stays_responsive_while_loading_largest_run(
    window, large_run, tmp_path
) -> None:
    run = clone(large_run, tmp_path / "large")
    ticks: list[float] = []
    timer = QtCore.QTimer()
    timer.setInterval(HEARTBEAT_MS)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    window.open_run(run)
    assert wait_until(lambda: not window.is_loading(), LOAD_TIMEOUT_S)
    timer.stop()
    assert len(ticks) > 2
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)]
    assert max(gaps) <= MAX_GAP_S, f"UI thread stalled {max(gaps):.3f}s (R-19)"
    assert "Verified snapshot" in window.current_view.integrity_text


def test_tg11_cancel_returns_within_bound_and_leaks_nothing(window, large_run, tmp_path) -> None:
    run = clone(large_run, tmp_path / "large")
    before_fds = open_descriptors()
    window.open_run(run)
    assert wait_until(window.is_loading, 5.0)
    QtTest.QTest.qWait(100)
    started = time.monotonic()
    QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_Escape)
    assert wait_until(lambda: not window.is_loading(), CANCEL_BOUND_S + 1.0)
    assert time.monotonic() - started <= CANCEL_BOUND_S
    current = window.current_view
    assert current is None or "Cancelled" in current.integrity_text
    QtTest.QTest.qWait(50)
    assert open_descriptors() <= before_fds


def test_tg11_newer_selection_wins_over_stale_load(window, large_run, fresh, tmp_path) -> None:
    large = clone(large_run, tmp_path / "large")
    small = fresh("captured_success")
    window.open_run(large)
    assert wait_until(window.is_loading, 5.0)
    window.open_run(small)
    assert wait_until(lambda: not window.is_loading(), LOAD_TIMEOUT_S)
    QtTest.QTest.qWait(200)  # give any stale result a chance to arrive
    assert window.current_view is not None
    assert len(window.current_view.flows) == 1  # the small single-stream run, not the 4-stream


def test_tg11_close_during_load_is_deferred_then_completes(app, isolated_home, large_run, tmp_path):
    gui = importlib.import_module("diaglab.gui")
    window = gui.MainWindow()
    window.show()
    before_fds = open_descriptors()
    window.open_run(clone(large_run, tmp_path / "large"))
    assert wait_until(window.is_loading, 5.0)
    started = time.monotonic()
    window.close()
    # Never claims exit while the worker is alive: a still-loading window stays visible.
    if window.is_loading():
        assert window.isVisible()
    assert wait_until(lambda: not window.isVisible(), CANCEL_BOUND_S + 1.0)
    assert time.monotonic() - started <= CANCEL_BOUND_S
    assert not window.is_loading()
    QtTest.QTest.qWait(50)
    assert open_descriptors() <= before_fds
    assert files_under(isolated_home) == []


def test_tg11_worker_failures_surface_as_inspection_not_crash(window, tmp_path) -> None:
    run_view = open_and_wait(window, tmp_path / "does-not-exist")
    assert run_view is not None
    assert "Integrity failed" in run_view.integrity_text


# ---------------------------------------------------------------- UI-1 (review regression)


def _luminance(color) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.redF())
        + 0.7152 * channel(color.greenF())
        + 0.0722 * channel(color.blueF())
    )


def contrast(first, second) -> float:
    low, high = sorted((_luminance(first), _luminance(second)))
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_ui1_link_text_is_readable_in_both_themes(window, matrix, tmp_path, theme) -> None:
    """Summary values are rendered as links (UI-1): link colours, including any colour
    written into the rich text, must reach WCAG AA 4.5:1 on the panel background, and a
    theme switch after loading must not leave the previous theme's colour behind."""
    import re

    window.open_run(clone(matrix["four_omit"], tmp_path / "run"))
    assert wait_until(lambda: not window.is_loading(), LOAD_TIMEOUT_S)
    window.set_theme("dark" if theme == "light" else "light")
    window.set_theme(theme)
    QtTest.QTest.qWait(20)
    palette = window.palette()
    base = palette.color(QtGui.QPalette.ColorRole.Base)
    for role in (QtGui.QPalette.ColorRole.Link, QtGui.QPalette.ColorRole.LinkVisited):
        assert contrast(palette.color(role), base) >= 4.5, (theme, role)
    linked = [
        label.text()
        for label in window.findChildren(QtWidgets.QLabel)
        if "<a " in label.text() and label.isVisible()
    ]
    assert linked, "summary values are expected as links"
    for text in linked:
        for value in re.findall(r"color:\s*(#[0-9a-fA-F]{6})", text):
            assert contrast(QtGui.QColor(value), base) >= 4.5, (theme, value)


# ------------------------------------------- round 3 (UI-2, Gemini section 1.3 requests)


def _show_series(window, prefix: str):
    for index in range(window.series_select.count()):
        if window.series_select.itemText(index).startswith(prefix):
            window.series_select.setCurrentIndex(index)
            return window.series_select.itemData(index)
    pytest.fail(f"no series starting {prefix!r}")


def test_negative_warmup_bounds_are_unambiguous_in_details(window, fresh) -> None:
    """R-27 shifts warm-up to negative display time; '-2.0--1.0' or '-2.0–-1.0' reads as
    one garbled range. Display and raw bounds must both be shown, without sign collisions."""
    open_and_wait(window, fresh("four_omit"))
    series = _show_series(window, "Receiver goodput")
    warm = next(p for p in series.points if p.omitted)
    assert warm.start_s < 0 and warm.raw_start_s >= 0
    window.chart.point_selected.emit(warm)
    text = window.details.toPlainText()
    for collision in ("--", "–-", "—-", "-–"):
        assert collision not in text, text
    for value in (warm.start_s, warm.end_s, warm.raw_start_s, warm.raw_end_s):
        assert str(value) in text, (value, text)


def _teal_columns(image, top: int, bottom: int) -> list[bool]:
    def teal(color) -> bool:
        return abs(color.red() - 0x19) + abs(color.green() - 0xB8) + abs(color.blue() - 0xA6) < 90

    return [
        any(teal(image.pixelColor(x, y)) for y in range(top, bottom)) for x in range(image.width())
    ]


def _empty_runs(columns: list[bool]) -> list[tuple[int, int]]:
    """Teal-free column runs strictly between the first and last teal column."""
    lit = [x for x, value in enumerate(columns) if value]
    runs, start = [], None
    for x in range(lit[0], lit[-1] + 1):
        if not columns[x] and start is None:
            start = x
        elif columns[x] and start is not None:
            runs.append((start, x))
            start = None
    return runs


@pytest.mark.parametrize(("name", "gap"), [("gap", True), ("captured_success", False)])
def test_gap_is_not_bridged_by_the_drawn_line(window, fresh, name, gap) -> None:
    """R-8 at the pixel level: the gap fixture has 0.5 s missing between retained intervals
    2 and 3 (4.5 s span). No line may cross it. Contiguous captured data has no hole."""
    window.resize(1200, 800)
    open_and_wait(window, fresh(name))
    series = _show_series(window, "Receiver goodput · aggregate")
    QtTest.QTest.qWait(50)
    image = window.chart.grab().toImage()
    columns = _teal_columns(image, 30, image.height() - 50)
    runs = _empty_runs(columns)
    widest = max(runs, key=lambda r: r[1] - r[0], default=(0, 0))
    if not gap:
        assert widest[1] - widest[0] <= 3, runs
        return
    first, last = series.points[0].start_s, series.points[-1].end_s
    pairs = zip(series.points, series.points[1:], strict=False)
    hole = next((a.end_s, b.start_s) for a, b in pairs if b.break_before)
    lit = [x for x, value in enumerate(columns) if value]
    scale = (lit[-1] - lit[0]) / (last - first)
    expected = (hole[1] - hole[0]) * scale
    assert widest[1] - widest[0] >= 0.6 * expected, (runs, expected)
    centre = lit[0] + ((hole[0] + hole[1]) / 2 - first) * scale
    assert abs((widest[0] + widest[1]) / 2 - centre) <= 0.2 * expected, (widest, centre)
    # Sensitivity control: the same points without break flags must be bridged, proving the
    # hole above comes from honouring break_before and that this detector can see a bridge.
    window.chart.set_series(
        replace(series, points=tuple(replace(p, break_before=False) for p in series.points))
    )
    QtTest.QTest.qWait(50)
    image = window.chart.grab().toImage()
    bridged = _empty_runs(_teal_columns(image, 30, image.height() - 50))
    assert max((b - a for a, b in bridged), default=0) <= 3, bridged


def test_ui2_flow_identity_stays_readable_beside_unavailable_rtt(window, fresh) -> None:
    """UI-2: unavailable RTT cells must not squeeze the flow identity column; the cell may be
    short, but the full 'Unavailable: REASON' stays reachable (tooltip or details)."""
    window.resize(1000, 700)
    run_view = open_and_wait(window, fresh("four_derived"))
    QtTest.QTest.qWait(50)
    table = window.table
    assert table.rowCount() == len(run_view.flows) == 4
    assert table.horizontalScrollBarPolicy() != QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    metrics = table.fontMetrics()
    for row in range(table.rowCount()):
        identity = " ".join(table.item(row, 0).text().split()[:4])  # socket, src → dst
        assert "→" in identity
        assert table.columnWidth(0) >= metrics.horizontalAdvance(identity), identity
        for column in range(1, 4):  # mean/min/max RTT
            cell = table.item(row, column)
            assert cell.text().startswith("Unavailable"), cell.text()
            table.cellClicked.emit(row, column)
            reachable = cell.toolTip() + "\n" + window.details.toPlainText()
            assert "Unavailable: TCP_INFO_UNAVAILABLE" in reachable, reachable


MARKUP_REASON = '<a href="file:///etc/passwd">CONNECTION_TIMED_OUT</a><!-- hidden evidence -->'


def test_n1_status_labels_show_failure_reason_markup_literally(window, fresh) -> None:
    """N-1: failure_reason is any 1-256 char string, and checksums are not forgery
    protection (AUD-02). A self-consistent command.json carrying markup must appear in the
    status labels as the literal text, never as a rendered link or hidden comment."""
    run = fresh("connection_timeout")
    edit_json(run, "command.json", lambda record: record.update(failure_reason=MARKUP_REASON))
    rehash(run)
    run_view = open_and_wait(window, run)
    assert "Verified snapshot" in run_view.integrity_text
    assert MARKUP_REASON in run_view.traffic_text
    labels = (window.integrity, window.traffic, window.eligibility)
    assert MARKUP_REASON in window.traffic.text()
    for label in labels:
        assert label.textFormat() == QtCore.Qt.TextFormat.PlainText, label.text()
    # Rendered width must cover every literal character. As rich text the tags and comment
    # vanish; the control below proves that this width check notices.
    literal = window.traffic.fontMetrics().horizontalAdvance(window.traffic.text())
    assert window.traffic.sizeHint().width() >= literal
    window.traffic.setTextFormat(QtCore.Qt.TextFormat.RichText)
    try:
        assert window.traffic.sizeHint().width() < literal
    finally:
        window.traffic.setTextFormat(QtCore.Qt.TextFormat.PlainText)
