# tools/index_tab_tool.py — 인덱스 포스트잇(책갈피 탭) 도구
"""클릭한 페이지에 색깔 있는 책갈피(인덱스 탭)를 붙인다.

인덱스 탭은 PDF 표준 책갈피(TOC)로 저장되며, 캔버스 오른쪽의 사이드 바에
'모든 페이지에서' 항상 표시된다. 다른 페이지를 보다가 탭을 클릭하면 그
페이지로 바로 이동한다 — 실제 인덱스 포스트잇처럼.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QPointF, QSize
from PySide6.QtGui import QMouseEvent, QColor, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDialogButtonBox,
    QPushButton, QButtonGroup, QWidget, QGridLayout, QRadioButton,
)

from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_pt

# 포스트잇 인덱스 색상 팔레트 (라벨, RGB 0~1)
_PALETTE = [
    ('분홍', (0.96, 0.55, 0.65)),
    ('노랑', (1.00, 0.89, 0.43)),
    ('초록', (0.56, 0.82, 0.56)),
    ('파랑', (0.36, 0.68, 0.94)),
    ('하늘', (0.50, 0.83, 0.91)),
    ('보라', (0.72, 0.61, 0.88)),
    ('주황', (0.96, 0.65, 0.36)),
    ('빨강', (0.91, 0.36, 0.36)),
]


def _swatch_icon(rgb: tuple[float, float, float], size: int = 26) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
    p.setBrush(col)
    p.setPen(QColor(0, 0, 0, 60))
    p.drawRoundedRect(1, 1, size-2, size-2, 4, 4)
    p.end()
    return QIcon(pm)


class _IndexTabDialog(QDialog):
    def __init__(self, parent=None, initial_text: str = '',
                 initial_color=None, target_page: int | None = None,
                 initial_side: str = 'right'):
        super().__init__(parent)
        self.setWindowTitle('인덱스 포스트잇 수정' if initial_text else '인덱스 포스트잇 추가')
        self.setMinimumWidth(320)
        self._color = tuple(initial_color) if initial_color else _PALETTE[3][1]

        lay = QVBoxLayout(self)
        lay.setSpacing(9)

        if target_page is not None:
            info = QLabel(f'📑 {target_page + 1}쪽에 인덱스(책갈피)를 붙입니다.')
            info.setStyleSheet('color:#555;')
            lay.addWidget(info)

        lay.addWidget(QLabel('라벨 (짧게)'))
        self._edit = QLineEdit()
        self._edit.setText(initial_text)
        self._edit.setPlaceholderText('예: 3장, 중요, Check')
        self._edit.returnPressed.connect(self.accept)
        lay.addWidget(self._edit)

        lay.addWidget(QLabel('색상'))
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._color_group = QButtonGroup(self)
        self._color_group.setExclusive(True)
        for i, (label, rgb) in enumerate(_PALETTE):
            b = QPushButton()
            b.setCheckable(True)
            b.setIcon(_swatch_icon(rgb, 26))
            b.setIconSize(QSize(26, 26))
            b.setFixedSize(38, 34)
            b.setToolTip(label)
            b.clicked.connect(lambda _c=False, _rgb=rgb: setattr(self, '_color', _rgb))
            if tuple(rgb) == tuple(self._color):
                b.setChecked(True)
            self._color_group.addButton(b, i)
            grid.addWidget(b, i // 4, i % 4)
        lay.addWidget(grid_w)

        # 붙일 위치 (왼쪽/오른쪽 가장자리)
        side_row = QHBoxLayout()
        side_row.addWidget(QLabel('붙일 쪽'))
        self._rb_right = QRadioButton('오른쪽 ▶')
        self._rb_left = QRadioButton('◀ 왼쪽')
        (self._rb_left if initial_side == 'left' else self._rb_right).setChecked(True)
        side_row.addWidget(self._rb_left)
        side_row.addWidget(self._rb_right)
        side_row.addStretch(1)
        lay.addLayout(side_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._edit.setFocus()

    def label_text(self) -> str:
        return self._edit.text().strip()

    def color(self) -> tuple[float, float, float]:
        return self._color

    def side(self) -> str:
        return 'left' if self._rb_left.isChecked() else 'right'


class IndexTabTool(BaseTool):
    name     = 'index_tab'
    label    = '🔖 인덱스'
    cursor   = Qt.CursorShape.PointingHandCursor
    shortcut = ''

    def __init__(self):
        self._last_color = _PALETTE[3][1]
        self._last_side = 'right'

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def on_press(self, pos, event, view):
        pass

    def on_move(self, pos, event, view):
        pass

    def on_release(self, pos: QPointF, event: QMouseEvent, view):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not view.doc().is_open:
            return
        # 클릭한 위치의 페이지를 책갈피 대상으로
        page_idx, _pt = resolve_page_and_fitz_pt(view, pos)
        default_label = f'{page_idx + 1}쪽'
        dlg = _IndexTabDialog(view, initial_color=self._last_color,
                              target_page=page_idx, initial_side=self._last_side)
        dlg._edit.setText(default_label)
        dlg._edit.selectAll()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        label = dlg.label_text() or default_label
        color = dlg.color()
        side = dlg.side()
        self._last_color = color
        self._last_side = side
        view.doc().add_index_tab(page_idx, label, color, side=side)
