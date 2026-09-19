# ui/page_slide_bar.py — 하단 페이지 이동 슬라이더 (평소 숨김, hover 시 노출)
"""화면 하단 가장자리에 얇게 숨어 있다가 마우스를 대면 천천히 올라오는 페이지
이동 슬라이더. 드래그하는 동안 목표 페이지를 크게 보여 주고, 손을 떼면 그
페이지로 이동한다(원하는 페이지에 정확히 착지). 마우스가 벗어나면 유예 시간
뒤에 다시 숨는다."""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QPoint, QTimer, Signal, QPropertyAnimation, QEasingCurve, QRectF,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont
from PySide6.QtWidgets import QWidget, QSlider, QLabel

_STRIP_H = 8         # 숨김 상태에서 하단에 보이는 띠 높이
_OPEN_H = 52         # 펼쳤을 때 높이
_SIDE_PAD = 18


class PageSlideBar(QWidget):
    navigate = Signal(int)   # 대상 페이지(0-based)

    def __init__(self, canvas):
        super().__init__(canvas.viewport())
        self._canvas = canvas
        self._count = 0
        self._open = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(1)      # 트랙 클릭도 한 페이지씩만(과도한 점프 방지)
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.setStyleSheet(self._SLIDER_QSS)
        self._slider.valueChanged.connect(self._on_value)
        self._slider.sliderReleased.connect(self._on_released)

        self._badge = QLabel(self)       # 드래그 중 '페이지 N / 총' 크게 표시
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont('Malgun Gothic'); f.setPixelSize(15); f.setBold(True)
        self._badge.setFont(f)
        self._badge.setStyleSheet(
            'background: rgba(30,32,38,235); color: #fff;'
            'border-radius: 8px; padding: 4px 12px;')
        self._badge.hide()

        self._anim = QPropertyAnimation(self, b'pos', self)
        self._anim.setDuration(520)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._close_timer = QTimer(self); self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(650)
        self._close_timer.timeout.connect(self._maybe_close)
        self.hide()

    _SLIDER_QSS = """
        QSlider::groove:horizontal { height: 5px; border-radius: 2px;
            background: rgba(150,150,160,150); }
        QSlider::sub-page:horizontal { height: 5px; border-radius: 2px;
            background: rgba(60,130,200,230); }
        QSlider::handle:horizontal { width: 16px; height: 16px;
            margin: -6px 0; border-radius: 8px;
            background: #ffffff; border: 2px solid rgba(60,130,200,240); }
    """

    # ── 데이터 ────────────────────────────────────────────────────────
    def set_page_count(self, n: int):
        self._count = max(0, int(n))
        self._slider.blockSignals(True)
        self._slider.setMaximum(max(0, self._count - 1))
        self._slider.blockSignals(False)
        if self._count <= 1:
            self.hide()
        else:
            self.reposition()
            self.show(); self.raise_()

    def set_current_page(self, page: int):
        if self._slider.isSliderDown():
            return          # 사용자가 드래그 중이면 방해하지 않음
        self._slider.blockSignals(True)
        self._slider.setValue(max(0, min(int(page), self._slider.maximum())))
        self._slider.blockSignals(False)

    # ── 배치 ──────────────────────────────────────────────────────────
    def reposition(self):
        vp = self._canvas.viewport()
        w = vp.width()
        self.resize(w, _OPEN_H)
        y = (vp.height() - _OPEN_H) if self._open else (vp.height() - _STRIP_H)
        self.move(0, y)
        self._slider.setGeometry(_SIDE_PAD, _OPEN_H - 26,
                                 max(50, w - 2 * _SIDE_PAD), 22)

    def _target_y(self) -> int:
        vp = self._canvas.viewport()
        return (vp.height() - _OPEN_H) if self._open else (vp.height() - _STRIP_H)

    def _animate(self):
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(0, self._target_y()))
        self._anim.start()

    # ── 상호작용 ──────────────────────────────────────────────────────
    def enterEvent(self, _e):
        self._close_timer.stop()
        if not self._open:
            self._open = True
            self._animate()

    def leaveEvent(self, _e):
        if self._open and not self._slider.isSliderDown():
            self._close_timer.start()

    def _maybe_close(self):
        if self._open and not self._slider.isSliderDown() and not self.underMouse():
            self._open = False
            self._badge.hide()
            self._animate()

    def _on_value(self, v: int):
        self._show_badge(v)
        if not self._slider.isSliderDown():
            # 트랙 클릭·키보드 등 즉시 확정 이동
            self.navigate.emit(v)

    def _on_released(self):
        self._badge.hide()
        self.navigate.emit(self._slider.value())

    def _show_badge(self, v: int):
        if self._count <= 1:
            return
        self._badge.setText(f'  {v + 1} / {self._count}  ')
        self._badge.adjustSize()
        # 핸들 위쪽에 배지를 띄운다
        gr = self._slider.geometry()
        ratio = v / max(1, self._slider.maximum())
        hx = gr.x() + int(ratio * gr.width())
        bx = max(4, min(self.width() - self._badge.width() - 4,
                        hx - self._badge.width() // 2))
        self._badge.move(bx, 2)
        self._badge.show(); self._badge.raise_()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 펼쳐진 부분 배경(위쪽 둥근 반투명 패널)
        if self._open or True:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 6, self.width(), _OPEN_H), 10, 10)
            p.fillPath(path, QColor(245, 245, 248, 235 if self._open else 0))
        # 항상 보이는 하단 잡이 띠(가운데 짧은 막대)
        gw = 46
        p.fillPath(self._pill((self.width() - gw) / 2, 2.5, gw, 3.5),
                   QColor(120, 120, 130, 200))
        p.end()

    @staticmethod
    def _pill(x, y, w, h):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        return path
