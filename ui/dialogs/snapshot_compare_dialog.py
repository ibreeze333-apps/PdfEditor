# ui/dialogs/snapshot_compare_dialog.py
# 두 스냅샷을 나란히 비교하는 다이얼로그
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QWidget, QPushButton, QSplitter,
    QSizePolicy, QSlider, QListWidget, QListWidgetItem,
    QAbstractItemView, QFrame,
)
from PySide6.QtGui import QIcon


class _ImagePanel(QScrollArea):
    """스냅샷 하나를 보여주는 스크롤 가능한 패널."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumSize(300, 300)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._title_lbl = QLabel(title)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet(
            'font-weight: 700; font-size: 12px; '
            'background: #f0f0f0; border-radius: 4px; padding: 4px;')
        layout.addWidget(self._title_lbl)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setScaledContents(False)
        self._img_lbl.setMinimumSize(200, 200)
        self._img_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._img_lbl, 1)

        self._info_lbl = QLabel('이미지 없음')
        self._info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_lbl.setStyleSheet('color: #888; font-size: 11px;')
        layout.addWidget(self._info_lbl)

        self.setWidget(container)
        self._pixmap: QPixmap | None = None
        self._scale = 1.0

    def set_pixmap(self, px: QPixmap, label: str = ''):
        self._pixmap = px
        self._info_lbl.setText(
            f'{px.width()} × {px.height()} px' +
            (f'  |  {label}' if label else ''))
        self._apply_scale()

    def set_scale(self, scale: float):
        self._scale = max(0.1, min(5.0, scale))
        self._apply_scale()

    def _apply_scale(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        w = max(1, int(self._pixmap.width() * self._scale))
        h = max(1, int(self._pixmap.height() * self._scale))
        scaled = self._pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._img_lbl.setPixmap(scaled)


class SnapshotCompareDialog(QDialog):
    """두 스냅샷을 나란히 비교하는 다이얼로그."""

    def __init__(self, snapshots: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle('스냅샷 비교')
        self.resize(1100, 720)
        self.setMinimumSize(700, 500)
        self._snapshots = snapshots  # list of {'pixmap': QPixmap, 'label': str}
        self._scale = 1.0
        self._build_ui()
        if len(snapshots) >= 2:
            self._left_list.setCurrentRow(0)
            self._right_list.setCurrentRow(1)
            self._on_left_selected()
            self._on_right_selected()
        elif len(snapshots) == 1:
            self._left_list.setCurrentRow(0)
            self._on_left_selected()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── 상단: 스냅샷 선택 패널 (좌/우 각각) ──────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        left_box = self._make_pick_box('왼쪽 선택', 'left')
        right_box = self._make_pick_box('오른쪽 선택', 'right')
        top_row.addWidget(left_box)
        top_row.addWidget(right_box)
        root.addLayout(top_row)

        # ── 확대/축소 슬라이더 ────────────────────────────────────
        zoom_row = QHBoxLayout()
        zoom_lbl = QLabel('확대/축소:')
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 300)   # 10% ~ 300%
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedHeight(22)
        self._zoom_val_lbl = QLabel('100%')
        self._zoom_val_lbl.setFixedWidth(44)
        self._zoom_slider.valueChanged.connect(self._on_zoom)
        zoom_row.addWidget(zoom_lbl)
        zoom_row.addWidget(self._zoom_slider, 1)
        zoom_row.addWidget(self._zoom_val_lbl)
        root.addLayout(zoom_row)

        # ── 비교 패널 (좌우 분할) ─────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._panel_left  = _ImagePanel('← 왼쪽')
        self._panel_right = _ImagePanel('오른쪽 →')
        splitter.addWidget(self._panel_left)
        splitter.addWidget(self._panel_right)
        splitter.setSizes([500, 500])
        root.addWidget(splitter, 1)

        # ── 닫기 버튼 ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(self.accept)
        close_btn.setFixedWidth(80)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _make_pick_box(self, title: str, side: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setMaximumHeight(140)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        lbl = QLabel(title)
        lbl.setStyleSheet('font-weight: 600; font-size: 11px;')
        layout.addWidget(lbl)

        lw = QListWidget()
        lw.setIconSize(QSize(48, 48))
        lw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        for entry in self._snapshots:
            item = QListWidgetItem(entry.get('label', '스냅샷'))
            px = entry.get('pixmap')
            if px and not px.isNull():
                thumb = px.scaled(48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                item.setIcon(QIcon(thumb))
            lw.addItem(item)

        if side == 'left':
            self._left_list = lw
            lw.currentRowChanged.connect(self._on_left_selected)
        else:
            self._right_list = lw
            lw.currentRowChanged.connect(self._on_right_selected)

        layout.addWidget(lw, 1)
        return frame

    def _on_left_selected(self):
        row = self._left_list.currentRow()
        if 0 <= row < len(self._snapshots):
            e = self._snapshots[row]
            self._panel_left.set_pixmap(e['pixmap'], e.get('label', ''))
            self._panel_left.set_scale(self._scale)

    def _on_right_selected(self):
        row = self._right_list.currentRow()
        if 0 <= row < len(self._snapshots):
            e = self._snapshots[row]
            self._panel_right.set_pixmap(e['pixmap'], e.get('label', ''))
            self._panel_right.set_scale(self._scale)

    def _on_zoom(self, val: int):
        self._scale = val / 100.0
        self._zoom_val_lbl.setText(f'{val}%')
        self._panel_left.set_scale(self._scale)
        self._panel_right.set_scale(self._scale)
