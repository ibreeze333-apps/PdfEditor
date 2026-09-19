from __future__ import annotations

import io

import fitz
from PIL import Image, ImageFilter
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem

from tools.base_tool import BaseTool
from utils.annot_mapper import resolve_page_and_fitz_rect, scene_to_fitz_rect
from utils.annot_style import tool_style
from utils.pending_layer import PendingAnnotation

try:
    _RESAMPLE_NEAREST = Image.Resampling.NEAREST
    _RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
    _RESAMPLE_BOX = Image.Resampling.BOX
except AttributeError:
    _RESAMPLE_NEAREST = Image.NEAREST
    _RESAMPLE_BILINEAR = Image.BILINEAR
    _RESAMPLE_BOX = Image.BOX

_BLUR_MODE_LABELS = {
    'gaussian': '\uac15\ud55c \ube14\ub7ec',
    'pixelate': '\ud53d\uc140\ud654',
    'noise': '\ub178\uc774\uc988 \uc11e\uae30',
    'downscale': '\ucd95\uc18c \ud6c4 \uc7ac\ud655\ub300',
}


def _pixmap_from_png_bytes(image_bytes: bytes, width: float, height: float) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(image_bytes, 'PNG')
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        max(1, int(round(width))),
        max(1, int(round(height))),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _pixelate_image(image: Image.Image, strength: int) -> Image.Image:
    width, height = image.size
    block = max(4, int(round(strength * 1.8)))
    small = image.resize(
        (max(1, width // block), max(1, height // block)),
        _RESAMPLE_BOX,
    )
    return small.resize((width, height), _RESAMPLE_NEAREST)


def _downscale_image(image: Image.Image, strength: int) -> Image.Image:
    width, height = image.size
    factor = max(6, int(round(strength * 2.4)))
    small = image.resize(
        (max(1, width // factor), max(1, height // factor)),
        _RESAMPLE_BILINEAR,
    )
    return small.resize((width, height), _RESAMPLE_BILINEAR)


def _noise_mix_image(image: Image.Image, strength: int) -> Image.Image:
    base = image.filter(ImageFilter.GaussianBlur(radius=max(2.0, float(strength) * 0.8)))
    base = _pixelate_image(base, max(5, strength))
    noise = Image.effect_noise(image.size, max(32.0, float(strength) * 9.0)).convert('L')
    noise_rgb = Image.merge('RGB', (noise, noise, noise))
    alpha = min(0.45, 0.20 + strength * 0.012)
    return Image.blend(base, noise_rgb, alpha)


class MosaicTool(BaseTool):
    name = 'mosaic'
    label = '\U0001F58D \ub9c8\ucee4'
    cursor = Qt.CursorShape.CrossCursor
    shortcut = 'M'

    mode: str = 'marker'
    blur_mode: str = 'gaussian'
    blur_radius: int = 12

    def __init__(self):
        self._start: QPointF | None = None
        self._preview: QGraphicsRectItem | None = None
        self._settings_ref = None

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)
        self._settings_ref = getattr(view, '_settings', None)
        if self.mode == 'blur':
            self._sync_blur_preferences()

    def _sync_blur_preferences(self):
        settings = self._settings_ref
        if settings is None:
            return
        self.blur_mode = getattr(settings, 'blur_mode', self.blur_mode) or 'gaussian'
        self.blur_radius = int(getattr(settings, 'blur_strength', self.blur_radius) or self.blur_radius)

    def _store_blur_preferences(self):
        settings = self._settings_ref
        if settings is None:
            return
        settings.blur_mode = self.blur_mode
        settings.blur_strength = int(self.blur_radius)

    def blur_mode_label(self) -> str:
        return _BLUR_MODE_LABELS.get(self.blur_mode, _BLUR_MODE_LABELS['gaussian'])

    def on_press(self, pos: QPointF, event, view):
        self._start = pos
        item = QGraphicsRectItem()
        item.setZValue(50)
        if self.mode == 'blur':
            pen = QPen(QColor(65, 105, 225), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(90, 140, 255, 45)))
        else:
            marker_color = tool_style(self.name).color
            item.setPen(QPen(QColor(marker_color), 1.0))
            item.setBrush(QBrush(QColor(marker_color.red(), marker_color.green(), marker_color.blue(), 255)))
        view.scene().addItem(item)
        self._preview = item

    def on_move(self, pos: QPointF, event, view):
        if not (self._start and self._preview):
            return
        self._preview.setRect(QRectF(self._start, pos).normalized())

    def on_release(self, pos: QPointF, event, view):
        if not self._start:
            return
        rect_q = QRectF(self._start, pos).normalized()
        preview = self._preview
        self._preview = None
        self._start = None

        if rect_q.width() < 4 or rect_q.height() < 4:
            if preview:
                view.scene().removeItem(preview)
            return

        if self.mode == 'blur':
            if preview:
                view.scene().removeItem(preview)
            pending = self._make_blur_pending(rect_q, view)
            if pending is None:
                return
            view.pending_layer().add(pending)
            view.doc().mark_dirty()
            view.notify_pending_changed()
            return

        page_index, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        marker_color = tool_style(self.name).color
        if preview:
            preview.setPen(QPen(QColor(marker_color), 0.8))
            preview.setBrush(QBrush(QColor(marker_color.red(), marker_color.green(), marker_color.blue(), 255)))
        pending = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_index,
            tool_name=self.name,
            annot_type='rect',
            fitz_rect=fitz.Rect(fitz_rect),
            stroke_color=[marker_color.redF(), marker_color.greenF(), marker_color.blueF()],
            fill_color=[marker_color.redF(), marker_color.greenF(), marker_color.blueF()],
            opacity=1.0,
            border_width=0.1,
            q_item=preview,
        )
        view.pending_layer().add(pending)
        view.doc().mark_dirty()
        view.notify_pending_changed()

    def _make_blur_pending(self, rect_q: QRectF, view) -> PendingAnnotation | None:
        self._store_blur_preferences()
        page_idx, fitz_rect = resolve_page_and_fitz_rect(view, rect_q)
        page = view.doc().fitz_page(page_idx)
        render_zoom = 3.0
        pix = page.get_pixmap(
            matrix=fitz.Matrix(render_zoom, render_zoom),
            clip=fitz_rect,
            alpha=False,
        )
        if pix.width <= 0 or pix.height <= 0:
            return None

        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        result = self._apply_blur_style(img)

        buf = io.BytesIO()
        result.save(buf, format='PNG')
        image_bytes = buf.getvalue()

        preview_item = None
        pixmap = _pixmap_from_png_bytes(image_bytes, rect_q.width(), rect_q.height())
        if not pixmap.isNull():
            preview_item = QGraphicsPixmapItem(pixmap)
            preview_item.setPos(rect_q.x(), rect_q.y())
            preview_item.setZValue(50)
            preview_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            view.scene().addItem(preview_item)

        pending = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='image_bytes',
            fitz_rect=fitz_rect,
            q_item=preview_item,
        )
        setattr(pending, '_image_bytes', image_bytes)
        setattr(view, '_blur_used_in_session', True)
        return pending

    def _apply_blur_style(self, image: Image.Image) -> Image.Image:
        strength = max(4, int(self.blur_radius))
        mode = self.blur_mode or 'gaussian'
        if mode == 'pixelate':
            return _pixelate_image(image, strength)
        if mode == 'noise':
            return _noise_mix_image(image, strength)
        if mode == 'downscale':
            return _downscale_image(image, strength)
        return image.filter(ImageFilter.GaussianBlur(radius=max(3.0, float(strength) * 1.35)))


class BlurTool(MosaicTool):
    name = 'blur'
    label = '\U0001F4A7 \ube14\ub7ec'
    mode: str = 'blur'
    shortcut = 'B'
