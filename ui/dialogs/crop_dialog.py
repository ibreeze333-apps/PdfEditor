from __future__ import annotations

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from utils.annot_mapper import scene_to_fitz_rect
from utils.fitz_qt_bridge import render_page


class CropHandle(QGraphicsRectItem):
    SIZE = 10

    def __init__(self, name: str):
        super().__init__(-self.SIZE / 2, -self.SIZE / 2, self.SIZE, self.SIZE)
        self.name = name
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(0, 120, 255), 1.4))
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)


class CropView(QGraphicsView):
    def __init__(self, owner: "CropDialog"):
        super().__init__(owner)
        self._owner = owner
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._owner._fit_scene()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner._begin_interaction(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._owner._update_interaction(scene_pos)
            event.accept()
            return
        self._owner._update_hover(scene_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner._end_interaction(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CropDialog(QDialog):
    def __init__(self, page: fitz.Page, zoom: float = 1.0, parent=None):
        super().__init__(parent)
        self._page = page
        self._zoom = zoom
        self._result_rect: fitz.Rect | None = None
        self._page_rect = QRectF()
        self._current_rect = QRectF()
        self._mode: str | None = None
        self._active_handle: str | None = None
        self._drag_anchor = QPointF()
        self._drag_origin_rect = QRectF()
        self._drag_restore_rect = QRectF()
        self._min_size = 24.0
        self._crop_item: QGraphicsRectItem | None = None
        self._mask_items: list[QGraphicsRectItem] = []
        self._handles: dict[str, CropHandle] = {}

        self.setWindowTitle('\ud398\uc774\uc9c0 \uc790\ub974\uae30')
        self.setMinimumSize(760, 820)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('\ub9c8\uc6b0\uc2a4\ub85c \uc0c8 \uc601\uc5ed\uc744 \ub4dc\ub798\uadf8\ud558\uac70\ub098, \ubaa8\uc11c\ub9ac \ud578\ub4e4\uc744 \uc7a1\uc544 \ud06c\uae30\ub97c \uc870\uc808\ud558\uc138\uc694.'))

        self._scene = QGraphicsScene(self)
        self._view = CropView(self)
        self._view.setScene(self._scene)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._view)

        img = render_page(self._page, zoom=self._zoom)
        pxm = QPixmap.fromImage(img)
        bg = QGraphicsPixmapItem(pxm)
        bg.setZValue(0)
        self._scene.addItem(bg)

        self._page_rect = QRectF(0.0, 0.0, float(img.width()), float(img.height()))

        cb = self._page.cropbox
        initial = QRectF(
            cb.x0 * self._zoom,
            cb.y0 * self._zoom,
            max(self._min_size, cb.width * self._zoom),
            max(self._min_size, cb.height * self._zoom),
        ).intersected(self._page_rect)

        self._crop_item = QGraphicsRectItem()
        self._crop_item.setPen(QPen(QColor(0, 120, 255), 2.0, Qt.PenStyle.DashLine))
        self._crop_item.setBrush(QBrush(QColor(0, 120, 255, 36)))
        self._crop_item.setZValue(20)
        self._scene.addItem(self._crop_item)

        for _ in range(4):
            mask = QGraphicsRectItem()
            mask.setPen(QPen(Qt.PenStyle.NoPen))
            mask.setBrush(QBrush(QColor(0, 0, 0, 105)))
            mask.setZValue(10)
            self._scene.addItem(mask)
            self._mask_items.append(mask)

        for name in ('tl', 'tr', 'bl', 'br'):
            handle = CropHandle(name)
            self._scene.addItem(handle)
            self._handles[name] = handle

        self._set_crop_rect(initial)
        self._scene.setSceneRect(self._page_rect)
        self._fit_scene()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _fit_scene(self):
        if self._scene.sceneRect().isValid():
            self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _clamp_point(self, pos: QPointF) -> QPointF:
        return QPointF(
            min(max(pos.x(), self._page_rect.left()), self._page_rect.right()),
            min(max(pos.y(), self._page_rect.top()), self._page_rect.bottom()),
        )

    def _is_full_page_rect(self) -> bool:
        r = self._current_rect.normalized()
        p = self._page_rect
        return (
            abs(r.left() - p.left()) < 1.0
            and abs(r.top() - p.top()) < 1.0
            and abs(r.width() - p.width()) < 1.0
            and abs(r.height() - p.height()) < 1.0
        )

    def _handle_at(self, pos: QPointF) -> str | None:
        for name, handle in self._handles.items():
            if handle.sceneBoundingRect().adjusted(-4, -4, 4, 4).contains(pos):
                return name
        return None

    def _update_hover(self, pos: QPointF):
        handle = self._handle_at(pos)
        if handle in ('tl', 'br'):
            self._view.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            return
        if handle in ('tr', 'bl'):
            self._view.viewport().setCursor(Qt.CursorShape.SizeBDiagCursor)
            return
        if self._current_rect.adjusted(-3, -3, 3, 3).contains(pos):
            self._view.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            return
        self._view.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def _begin_interaction(self, pos: QPointF):
        pos = self._clamp_point(pos)
        self._drag_anchor = pos
        self._drag_origin_rect = QRectF(self._current_rect)
        self._drag_restore_rect = QRectF(self._current_rect)
        self._active_handle = self._handle_at(pos)

        if self._active_handle:
            self._mode = 'resize'
            self._update_hover(pos)
            return

        if self._current_rect.contains(pos) and not self._is_full_page_rect():
            self._mode = 'move'
            self._view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        self._mode = 'draw'
        self._view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._set_crop_rect(QRectF(pos, pos))

    def _update_interaction(self, pos: QPointF):
        pos = self._clamp_point(pos)
        if self._mode == 'draw':
            self._set_crop_rect(QRectF(self._drag_anchor, pos).normalized())
        elif self._mode == 'move':
            delta = pos - self._drag_anchor
            rect = QRectF(self._drag_origin_rect)
            rect.translate(delta)
            if rect.left() < self._page_rect.left():
                rect.moveLeft(self._page_rect.left())
            if rect.top() < self._page_rect.top():
                rect.moveTop(self._page_rect.top())
            if rect.right() > self._page_rect.right():
                rect.moveRight(self._page_rect.right())
            if rect.bottom() > self._page_rect.bottom():
                rect.moveBottom(self._page_rect.bottom())
            self._set_crop_rect(rect)
        elif self._mode == 'resize' and self._active_handle:
            self._set_crop_rect(self._resized_rect(self._drag_origin_rect, self._active_handle, pos))
        else:
            self._update_hover(pos)

    def _end_interaction(self, pos: QPointF):
        pos = self._clamp_point(pos)
        if self._mode == 'draw':
            if abs(pos.x() - self._drag_anchor.x()) < 4 and abs(pos.y() - self._drag_anchor.y()) < 4:
                self._set_crop_rect(self._drag_restore_rect)
        elif self._mode == 'resize' and self._active_handle:
            self._set_crop_rect(self._resized_rect(self._drag_origin_rect, self._active_handle, pos))
        self._mode = None
        self._active_handle = None
        self._update_hover(pos)

    def _resized_rect(self, origin: QRectF, handle: str, pos: QPointF) -> QRectF:
        p = self._page_rect
        left = origin.left()
        right = origin.right()
        top = origin.top()
        bottom = origin.bottom()

        if handle == 'tl':
            left = max(p.left(), min(pos.x(), right - self._min_size))
            top = max(p.top(), min(pos.y(), bottom - self._min_size))
        elif handle == 'tr':
            right = min(p.right(), max(pos.x(), left + self._min_size))
            top = max(p.top(), min(pos.y(), bottom - self._min_size))
        elif handle == 'bl':
            left = max(p.left(), min(pos.x(), right - self._min_size))
            bottom = min(p.bottom(), max(pos.y(), top + self._min_size))
        elif handle == 'br':
            right = min(p.right(), max(pos.x(), left + self._min_size))
            bottom = min(p.bottom(), max(pos.y(), top + self._min_size))

        return QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()

    def _set_crop_rect(self, rect: QRectF):
        rect = rect.normalized().intersected(self._page_rect)
        if rect.width() < self._min_size:
            rect.setWidth(self._min_size)
        if rect.height() < self._min_size:
            rect.setHeight(self._min_size)
        if rect.right() > self._page_rect.right():
            rect.moveRight(self._page_rect.right())
        if rect.bottom() > self._page_rect.bottom():
            rect.moveBottom(self._page_rect.bottom())
        if rect.left() < self._page_rect.left():
            rect.moveLeft(self._page_rect.left())
        if rect.top() < self._page_rect.top():
            rect.moveTop(self._page_rect.top())

        self._current_rect = rect
        self._crop_item.setRect(rect)
        self._update_handles()
        self._update_masks()

    def _update_handles(self):
        r = self._current_rect
        positions = {
            'tl': r.topLeft(),
            'tr': r.topRight(),
            'bl': r.bottomLeft(),
            'br': r.bottomRight(),
        }
        for name, point in positions.items():
            self._handles[name].setPos(point)

    def _update_masks(self):
        p = self._page_rect
        r = self._current_rect
        rects = [
            QRectF(p.left(), p.top(), p.width(), max(0.0, r.top() - p.top())),
            QRectF(p.left(), r.top(), max(0.0, r.left() - p.left()), max(0.0, r.height())),
            QRectF(r.right(), r.top(), max(0.0, p.right() - r.right()), max(0.0, r.height())),
            QRectF(p.left(), r.bottom(), p.width(), max(0.0, p.bottom() - r.bottom())),
        ]
        for item, rect in zip(self._mask_items, rects):
            item.setRect(rect)

    def _on_ok(self):
        rect_q = self._current_rect.normalized().intersected(self._page_rect)
        self._result_rect = scene_to_fitz_rect(rect_q, self._zoom)
        self.accept()

    def crop_rect(self) -> fitz.Rect | None:
        return self._result_rect
