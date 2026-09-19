# ui/screen_fit.py — 창·대화상자가 화면보다 크면 화면 안으로 맞춘다
"""작은 화면(예: 1920×1080 노트북 150% → 논리 1280×680)에서 대화상자가
화면 밖으로 넘쳐 아래쪽 버튼을 누를 수 없던 문제를 막는다.

여러 대화상자가 resize(900, 700), setMinimumSize(760, 820) 처럼 큰 크기를
직접 정해 두고 있었다. 최소 크기가 화면보다 크면 사용자가 줄일 수도 없다.
하나하나 고치는 대신 앱 전체에 필터를 걸어, 창이 뜰 때 화면의 작업 영역
(작업표시줄 제외)보다 크면 최소 크기를 낮추고 크기와 위치를 맞춘다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

_MARGIN = 8   # 화면 가장자리에 딱 붙지 않게 남기는 여백

# 이런 창은 건드리지 않는다 (메뉴·툴팁·스플래시 등)
_SKIP_TYPES = {
    Qt.WindowType.Popup, Qt.WindowType.ToolTip, Qt.WindowType.SplashScreen,
    Qt.WindowType.Desktop, Qt.WindowType.SubWindow,
}


def _available_rect(w: QWidget) -> QRect | None:
    screen = w.screen() or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def fit_to_screen(w: QWidget, avail: QRect | None = None) -> bool:
    """w 가 화면 작업 영역을 넘으면 줄이고 화면 안으로 옮긴다. 바꿨으면 True."""
    try:
        if not w.isWindow() or w.isMaximized() or w.isFullScreen():
            return False
    except RuntimeError:          # 이미 닫혀 파괴된 창
        return False
    avail = avail if avail is not None else _available_rect(w)
    if avail is None or avail.isEmpty():
        return False

    frame = w.frameGeometry()
    extra_w = max(0, frame.width() - w.width())     # 창 테두리·제목 표시줄
    extra_h = max(0, frame.height() - w.height())
    max_w = max(200, avail.width() - extra_w - 2 * _MARGIN)
    max_h = max(150, avail.height() - extra_h - 2 * _MARGIN)

    too_big = w.width() > max_w or w.height() > max_h
    off_screen = not avail.contains(frame)
    if not too_big and not off_screen:
        return False

    if w.minimumWidth() > max_w:
        w.setMinimumWidth(max_w)
    if w.minimumHeight() > max_h:
        w.setMinimumHeight(max_h)
    if too_big:
        w.resize(min(w.width(), max_w), min(w.height(), max_h))

    frame = w.frameGeometry()
    x = min(max(avail.left() + _MARGIN, frame.left()), avail.right() - frame.width() - _MARGIN + 1)
    y = min(max(avail.top() + _MARGIN, frame.top()), avail.bottom() - frame.height() - _MARGIN + 1)
    w.move(max(avail.left(), x), max(avail.top(), y))
    return True


class _ScreenFitFilter(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            kind = obj.windowType()
            if kind not in _SKIP_TYPES and not isinstance(obj, QMainWindow):
                # 창이 실제로 배치된 뒤(프레임 크기 확정 후)에 맞춘다
                QTimer.singleShot(0, lambda w=obj: fit_to_screen(w))
        return False


def install_screen_fit(app: QApplication) -> QObject:
    """앱 전체 창에 화면 맞춤을 건다. 돌려준 필터는 app 이 소유한다."""
    flt = _ScreenFitFilter(app)
    app.installEventFilter(flt)
    return flt
