"""Offline Qt workspace. All parsing and provenance live in the shared core."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from threading import Event

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diaglab.inspection import InspectionCode, InspectionIssue, load_run
from diaglab.presentation import build_view, filter_flows, sort_flows


class LoadWorker(QThread):
    progress = Signal(int, int)
    result_ready = Signal(object, object, int)
    failed = Signal(object)

    def __init__(self, path, generation, parent=None):
        super().__init__(parent)
        self.path, self.generation = path, generation
        self.cancel = Event()
        self.completed_result = None

    def run(self):
        inspection = load_run(self.path, cancel=self.cancel, progress=self.progress.emit)
        try:
            view = build_view(inspection)
            if self.cancel.is_set():
                inspection = load_run(self.path, cancel=self.cancel)
                view = build_view(inspection)
            self.completed_result = (inspection, view)
            self.result_ready.emit(inspection, view, self.generation)
        except Exception:
            self.failed.emit(
                InspectionIssue(
                    InspectionCode.INTERNAL_ERROR, None, "Unexpected display preparation failure"
                )
            )


class Timeline(QWidget):
    point_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = None
        self.bounds = None
        self.selected = None
        self.setMinimumHeight(230)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Wheel to zoom · double-click to reset · click an interval for evidence")

    def set_series(self, series):
        self.series, self.bounds, self.selected = series, None, None
        self.update()

    def _ranges(self):
        points = self.series.points if self.series else ()
        left = min((p.start_s for p in points), default=0)
        right = max((p.end_s for p in points), default=1)
        return self.bounds or (left, max(right, left + 0.001))

    def _area(self):
        return QRectF(75, 30, max(10, self.width() - 105), max(10, self.height() - 85))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        foreground = self.palette().color(QPalette.ColorRole.Text)
        if self.series is None or not self.series.points:
            painter.setPen(foreground)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No verified interval data available",
            )
            return
        left, right = self._ranges()
        points = [p for p in self.series.points if p.end_s >= left and p.start_s <= right]
        factor = 1e6 if self.series.unit == "Mbit/s" else 1
        maximum = max((p.value / factor for p in points if p.value is not None), default=1)
        maximum = max(maximum * 1.1, 1)

        def x(value):
            return area.left() + (value - left) / (right - left) * area.width()

        def y(value):
            return area.bottom() - value / factor / maximum * area.height()

        painter.setPen(QPen(QColor("#708399"), 0.5))
        for index in range(5):
            yy = area.bottom() - index / 4 * area.height()
            painter.drawLine(QPointF(area.left(), yy), QPointF(area.right(), yy))
            painter.setPen(foreground)
            painter.drawText(
                QRectF(0, yy - 9, 65, 20), Qt.AlignmentFlag.AlignRight, f"{maximum * index / 4:.1f}"
            )
            painter.setPen(QPen(QColor("#708399"), 0.5))
        painter.setPen(foreground)
        painter.drawText(
            QRectF(10, 0, self.width() - 20, 24), self.series.label + " (" + self.series.unit + ")"
        )
        ticks = [left + (right - left) * index / 4 for index in range(5)]
        if left < 0 < right:
            ticks[min(range(1, 4), key=lambda i: abs(ticks[i]))] = 0.0
        for tick in sorted(ticks):
            xx = x(tick)
            painter.drawText(
                QRectF(xx - 30, area.bottom() + 10, 65, 20),
                Qt.AlignmentFlag.AlignCenter,
                f"{tick:.2f}",
            )
        painter.drawText(
            QRectF(area.left(), self.height() - 22, area.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "Time (s)",
        )
        painter.save()
        painter.setClipRect(area)
        path = QPainterPath()
        connected = False
        # Each interval is rendered as a horizontal segment. No interpolation across gaps.
        for point in points:
            if point.omitted:
                painter.fillRect(
                    QRectF(
                        x(point.start_s),
                        area.top(),
                        max(1, x(point.end_s) - x(point.start_s)),
                        area.height(),
                    ),
                    QBrush(QColor(190, 135, 40, 70), Qt.BrushStyle.BDiagPattern),
                )
            if point.value is None:
                connected = False
                continue
            a, b = (
                QPointF(x(point.start_s), y(point.value)),
                QPointF(x(point.end_s), y(point.value)),
            )
            if not connected or point.break_before:
                path.moveTo(a)
            else:
                path.lineTo(a)
            path.lineTo(b)
            connected = True
        painter.setPen(QPen(QColor("#19b8a6"), 2))
        painter.drawPath(path)
        if self.selected is not None:
            painter.setPen(QPen(QColor("#f0b95f"), 1, Qt.PenStyle.DashLine))
            xx = x(self.selected.start_s)
            painter.drawLine(QPointF(xx, area.top()), QPointF(xx, area.bottom()))
        painter.restore()

    def wheelEvent(self, event):
        left, right = self._ranges()
        center = left + (event.position().x() - self._area().left()) / self._area().width() * (
            right - left
        )
        scale = 0.8 if event.angleDelta().y() > 0 else 1.25
        self.bounds = (center + (left - center) * scale, center + (right - center) * scale)
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.bounds = None
        self.update()

    def mousePressEvent(self, event):
        if not self.series or not self.series.points:
            return
        left, right = self._ranges()
        when = left + (event.position().x() - self._area().left()) / self._area().width() * (
            right - left
        )
        self.selected = min(self.series.points, key=lambda p: abs((p.start_s + p.end_s) / 2 - when))
        self.point_selected.emit(self.selected)
        self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_view = None
        self._inspection = None
        self._worker = None
        self._generation = 0
        self._pending = None
        self._closing = False
        self._result = None
        self._raw_page = 0
        self._raw_name = None
        self._rows = ()
        self._sort_column = None
        self._descending = False
        self.setWindowTitle("DiagLab · Network diagnostics")
        self.resize(1420, 900)
        self.setMinimumSize(1000, 700)
        self._build()
        self.set_theme("dark")
        self._poll = QTimer(self)
        self._poll.setInterval(15)
        self._poll.timeout.connect(self._finish_load)
        self._poll.start()

    def _build(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(14)
        top = QHBoxLayout()
        brand = QLabel("◈  DIAGLAB")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addWidget(QLabel("NETWORK DIAGNOSTICS  /  OFFLINE INSPECTOR"))
        top.addStretch()
        self.open_button = QPushButton("Open run…")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open_dialog)
        top.addWidget(self.open_button)
        self.cancel_button = QPushButton("Cancel loading")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_load)
        top.addWidget(self.cancel_button)
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.currentTextChanged.connect(lambda text: self.set_theme(text.lower()))
        top.addWidget(self.theme)
        layout.addLayout(top)
        self.path_label = QLabel("Your evidence, in context. Open a saved run to begin.")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setObjectName("path")
        layout.addWidget(self.path_label)
        statuses = QHBoxLayout()
        self.integrity = QLabel("○ No snapshot")
        self.traffic = QLabel("○ No traffic record")
        self.eligibility = QLabel("○ No eligibility record")
        for label in (self.integrity, self.traffic, self.eligibility):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setObjectName("status")
            statuses.addWidget(label)
        layout.addLayout(statuses)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter flows by address, port, socket or quality flag…")
        self.filter.textChanged.connect(self._filter_rows)
        layout.addWidget(self.filter)
        panes = QSplitter(Qt.Orientation.Horizontal)
        self.navigation = QTreeWidget()
        self.navigation.setHeaderLabels(["RUN EVIDENCE"])
        self.navigation.setMinimumWidth(190)
        self.navigation.itemClicked.connect(self._select_artifact)
        panes.addWidget(self.navigation)
        workspace = QWidget()
        main = QVBoxLayout(workspace)
        main.setContentsMargins(8, 0, 8, 0)
        self.summary = QLabel("No measurements loaded")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.summary.linkActivated.connect(self._summary_details)
        self.summary.setObjectName("summary")
        main.addWidget(self.summary)
        self.tabs = QTabWidget()
        timeline = QWidget()
        timeline_layout = QVBoxLayout(timeline)
        self.series_select = QComboBox()
        self.series_select.currentIndexChanged.connect(self._select_series)
        timeline_layout.addWidget(self.series_select)
        self.chart = Timeline()
        self.chart.point_selected.connect(self._point_details)
        timeline_layout.addWidget(self.chart)
        timeline_layout.addWidget(
            QLabel("Warm-up intervals shaded · wheel to zoom · double-click to reset")
        )
        self.tabs.addTab(timeline, "Timeline")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        raw_panel = QWidget()
        raw_layout = QVBoxLayout(raw_panel)
        raw_layout.addWidget(self.raw)
        pages = QHBoxLayout()
        for text, delta in [("Previous page", -1), ("Next page", 1)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, d=delta: self._page(d))
            pages.addWidget(button)
        raw_layout.addLayout(pages)
        self.tabs.addTab(raw_panel, "Raw evidence")
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.tabs.addTab(self.events, "Event log")
        self.coverage = QPlainTextEdit()
        self.coverage.setReadOnly(True)
        self.tabs.addTab(self.coverage, "Collectors")
        main.addWidget(self.tabs, 3)
        self.table = QTableWidget(0, 5)
        self.table.verticalHeader().hide()
        self.table.setHorizontalHeaderLabels(
            ["Flow / endpoints", "Mean RTT (µs)", "Min RTT (µs)", "Max RTT (µs)", "Retransmits"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 330)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_rows)
        self.table.cellClicked.connect(self._flow_details)
        main.addWidget(self.table, 2)
        panes.addWidget(workspace)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(
            "Select a flow, interval or artifact to inspect its source."
        )
        self.details.setMinimumWidth(230)
        panes.addWidget(self.details)
        panes.setSizes([210, 850, 300])
        layout.addWidget(panes, 1)
        self.statusBar().showMessage("Offline workspace · local files only")
        open_action = QAction("Open run", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._open_dialog)
        self.addAction(open_action)
        cancel = QAction("Cancel loading", self)
        cancel.setShortcut(QKeySequence("Escape"))
        cancel.triggered.connect(self.cancel_load)
        self.addAction(cancel)
        self.setTabOrder(self.open_button, self.filter)
        self.setTabOrder(self.filter, self.navigation)
        self.setTabOrder(self.navigation, self.table)
        self.setTabOrder(self.table, self.details)

    def set_theme(self, theme):
        if theme not in ("light", "dark"):
            raise ValueError("theme must be light or dark")
        dark = theme == "dark"
        self._link_color = "#65ded0" if dark else "#006b63"
        bg, panel, text, muted, border = (
            ("#101720", "#192330", "#e6edf4", "#a5b4c5", "#344457")
            if dark
            else ("#eef2f6", "#ffffff", "#1c2c3f", "#53677b", "#c9d4df")
        )
        palette = QPalette()
        for role, color in [
            (QPalette.ColorRole.Window, bg),
            (QPalette.ColorRole.Base, panel),
            (QPalette.ColorRole.AlternateBase, bg),
            (QPalette.ColorRole.Text, text),
            (QPalette.ColorRole.WindowText, text),
            (QPalette.ColorRole.Button, panel),
            (QPalette.ColorRole.ButtonText, text),
            (QPalette.ColorRole.Highlight, "#167f84"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
            (QPalette.ColorRole.Link, "#65ded0" if dark else "#006b63"),
            (QPalette.ColorRole.LinkVisited, "#b8b0ff" if dark else "#6040a0"),
        ]:
            palette.setColor(role, QColor(color))
        self.setStyleSheet(f"""
            QWidget {{font-family: "DejaVu Sans"; font-size: 12px; color: {text};}}
            QMainWindow, QWidget#central {{background: {bg};}}
            QLabel#brand {{font-size:22px; font-weight:700; letter-spacing:2px; color:#19b8a6;}}
            QLabel#path {{color:{muted}; padding:4px 0;}}
            QLabel#status {{background:{panel}; border:1px solid {border}; border-radius:7px;
                padding:12px;}}
            QLabel#summary {{background:{panel}; padding:16px; border-radius:8px; font-size:14px;}}
            QLineEdit,QPlainTextEdit,QTreeWidget,QTableWidget {{background:{panel};
                border:1px solid {border}; border-radius:5px; padding:6px;}}
            QPushButton,QComboBox {{background:{panel}; border:1px solid {border};
                border-radius:5px; padding:8px 12px;}}
            QPushButton#primary {{background:#137e7b; color:white; border:none;}}
            QPushButton:disabled {{color:{muted};}}
            QHeaderView::section {{background:{bg}; color:{muted}; padding:8px; border:none;}}
            QHeaderView {{background:{bg};}}
            QTabWidget::pane {{border:1px solid {border};}}
            QTabBar::tab {{padding:9px 15px; background:{bg};}}
            QTabBar::tab:selected {{background:{panel}; border-bottom:2px solid #19b8a6;}}
        """)
        self.setPalette(palette)
        self.chart.update()
        if self.current_view is not None:
            self._render_summary()

    def _open_dialog(self):
        # A small path dialog avoids file-dialog history writes and hidden directory scans.
        dialog = QDialog(self)
        dialog.setWindowTitle("Open saved run")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Run directory"))
        path = QLineEdit()
        path.setPlaceholderText("/path/to/saved/run")
        path.setMinimumWidth(520)
        layout.addWidget(path)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and path.text().strip():
            self.open_run(Path(path.text().strip()))

    def is_loading(self):
        return self._worker is not None

    def open_run(self, path):
        self._generation += 1
        self._pending = (Path(path), self._generation)
        if self._worker is not None:
            self._worker.cancel.set()
            self.statusBar().showMessage("Cancelling previous load…")
        else:
            self._begin_load()

    def _begin_load(self):
        if self._pending is None or self._closing:
            return
        path, generation = self._pending
        self._pending = None
        self._result = None
        self.cancel_button.setEnabled(True)
        self.statusBar().showMessage("Reading and verifying snapshot…")
        worker = LoadWorker(path, generation, self)
        self._worker = worker
        worker.progress.connect(
            lambda done, total: self.statusBar().showMessage(
                f"Reading snapshot · {done}/{total} artifacts"
            )
        )
        worker.result_ready.connect(self._receive)
        worker.failed.connect(lambda issue: self.statusBar().showMessage(issue.message))
        worker.start()

    def _receive(self, inspection, view, generation):
        if generation == self._generation:
            self._result = (inspection, view)

    def cancel_load(self):
        self._pending = None
        if self._worker is not None:
            self._worker.cancel.set()
            self.statusBar().showMessage("Cancelling…")

    def _finish_load(self):
        worker = self._worker
        if worker is None or worker.isRunning():
            return
        worker.wait()
        # Thread completion can race delivery of the queued result signal.
        if worker.generation == self._generation:
            self._result = worker.completed_result
            if worker.cancel.is_set() and not self._closing:
                cancelled = load_run(worker.path, cancel=worker.cancel)
                self._result = (cancelled, build_view(cancelled))
        if self._result is not None and not self._closing:
            self._inspection, self.current_view = self._result
            self.path_label.setText(
                str(worker.path) + "  ·  Loaded " + datetime.now().strftime("%H:%M:%S")
            )
            self._render()
        self._result = None
        self._worker = None
        worker.deleteLater()
        self.cancel_button.setEnabled(False)
        if self._closing:
            self.close()
        elif self._pending:
            self._begin_load()

    def _render(self):
        view = self.current_view
        self.integrity.setText("◈ " + view.integrity_text)
        self.traffic.setText("↔ " + view.traffic_text)
        self.eligibility.setText("◇ " + view.eligibility_text)
        self._render_summary()
        self._render_content(view)

    def _render_summary(self):
        color = self._link_color
        self.summary.setText(
            "<br>".join(
                f'{escape(v.label)} &nbsp; <a href="{index}" style="color:{color}">'
                f"{escape(v.text)} ↗</a>"
                for index, v in enumerate(self.current_view.summary)
            )
            or "No verified measurements available"
        )

    def _render_content(self, view):
        self.series_select.clear()
        for series in view.series:
            self.series_select.addItem(series.label, series)
        preferred = next(
            (i for i, s in enumerate(view.series) if s.label == "Receiver goodput · aggregate"), 0
        )
        self.series_select.setCurrentIndex(preferred)
        self.navigation.clear()
        parent = QTreeWidgetItem(self.navigation, ["Artifacts"])
        for item in view.raw_artifacts:
            node = QTreeWidgetItem(parent, [item.name])
            node.setData(0, Qt.ItemDataRole.UserRole, item.name)
        parent.setExpanded(True)
        self.events.setPlainText(
            "\n".join(
                f"{e.get('timestamp_utc', '')}  {e.get('name', '')}  {e.get('message', '')}"
                for e in view.events
            )
        )
        self.coverage.setPlainText(
            "\n".join(f"{v.label}: {v.text}" for v in view.collectors)
            or "No verified collector records available"
        )
        self._filter_rows()
        self.details.setPlainText(
            "\n".join(f"{i.code}: {i.message}" for i in self._inspection.issues)
            or "Select a flow or chart interval to inspect its evidence."
        )
        self.raw.clear()
        self._raw_name = None
        self.statusBar().showMessage(
            view.integrity_text + " · Snapshot values are fixed at load time"
        )

    def _select_series(self, index):
        self.chart.set_series(self.series_select.itemData(index) if index >= 0 else None)

    def _filter_rows(self):
        if self.current_view is None:
            return
        rows = filter_flows(self.current_view, self.filter.text())
        if rows and self._sort_column:
            rows = sort_flows(rows, self._sort_column, descending=self._descending)
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(row.search_text))
            for j, value in enumerate(row.values, 1):
                cell = QTableWidgetItem("Unavailable" if value.value is None else value.text)
                cell.setToolTip(value.text)
                self.table.setItem(i, j, cell)

    def _sort_rows(self, column):
        if not self._rows or column == 0:
            return
        label = self._rows[0].values[column - 1].label
        self._descending = not self._descending if label == self._sort_column else False
        self._sort_column = label
        self._filter_rows()

    def _evidence_text(self, refs):
        if not refs:
            return "Evidence reference unavailable"
        lines = []
        for ref in refs:
            lines.extend(
                [
                    f"Artifact: {ref.artifact}",
                    f"JSON pointer: {ref.json_pointer}",
                    f"SHA-256: {ref.sha256}",
                    f"Source: {ref.source}",
                    f"Derivation: {ref.derivation or 'direct value'}",
                ]
            )
            lines.extend("Input: " + pointer for pointer in ref.inputs)
        return "\n".join(lines)

    def _flow_details(self, row, column):
        item = self._rows[row]
        if column:
            value = item.values[column - 1]
            self.details.setPlainText(
                f"{value.label}\n{value.text}\nExact value: {value.value!r}\n\n"
                + self._evidence_text(value.evidence)
            )
        else:
            self.details.setPlainText(
                item.search_text + "\n\n" + "\n".join(f"{v.label}: {v.text}" for v in item.values)
            )

    def _point_details(self, point):
        series = self.chart.series
        unit = "bps" if series and series.unit == "Mbit/s" else "µs"
        self.details.setPlainText(
            f"Display interval: [{point.start_s}, {point.end_s}] s\n"
            f"Raw JSON interval: [{point.raw_start_s}, {point.raw_end_s}] s\n"
            f"Exact value: {point.value!r} {unit}\n"
            + ("Omitted warm-up\n" if point.omitted else "")
            + self._evidence_text(point.evidence)
        )

    def _summary_details(self, index):
        if self.current_view is None:
            return
        value = self.current_view.summary[int(index)]
        unit = "bps" if value.unit == "Mbit/s" else value.unit
        self.details.setPlainText(
            f"{value.label}\n{value.text}\nExact value: {value.value!r} {unit}\n\n"
            + self._evidence_text(value.evidence)
        )

    def _select_artifact(self, item, column):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self._raw_name = name
            self._raw_page = 0
            self._show_raw()
            self.tabs.setCurrentIndex(1)

    def _page(self, delta):
        self._raw_page = max(0, self._raw_page + delta)
        self._show_raw()

    def _show_raw(self):
        if self.current_view is None or not self._raw_name:
            return
        item = next(a for a in self.current_view.raw_artifacts if a.name == self._raw_name)
        if item.data is None:
            self.raw.setPlainText(item.issue.message if item.issue else "Unavailable")
            return
        size = 65536
        self._raw_page = min(self._raw_page, max(0, (len(item.data) - 1) // size))
        chunk = item.data[self._raw_page * size : (self._raw_page + 1) * size]
        text = chunk.decode("utf-8", errors="replace")
        status = (
            "Verified snapshot raw evidence"
            if self._inspection.integrity == "verified"
            else "Unverified raw evidence"
        )
        self.raw.setPlainText(
            f"{status} · page {self._raw_page + 1}\n"
            + ("Replacement characters used\n" if "\ufffd" in text else "")
            + text
        )
        self.details.setPlainText(
            f"{item.name}\n{status}\nSHA-256: {item.sha256}\n"
            f"Expected SHA-256: {item.expected_sha256 or 'Not listed'}\n"
            f"File digest: {item.digest_status}\nSize: {item.size_bytes} B"
        )

    def closeEvent(self, event):
        if self._worker is not None:
            self._closing = True
            self._pending = None
            self.cancel_load()
            event.ignore()
        else:
            event.accept()
