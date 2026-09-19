# tools/note_tool.py — 스티키 메모
from __future__ import annotations
import fitz
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QMouseEvent, QPen, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QGraphicsRectItem, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QDialogButtonBox, QSpinBox, QSlider,
    QGraphicsItemGroup, QGraphicsTextItem,
)
from tools.base_tool import BaseTool
from tools.select_tool import ExistingSelectionDelegate
from ui.font_combo import FontPickerCombo
from utils.annot_mapper import resolve_page_and_fitz_pt
from utils.pending_layer import PendingAnnotation

_DEFAULT_FAMILY = 'Malgun Gothic'
_DEFAULT_SIZE   = 12


def measure_note_rect(text: str, family: str, fontsize: float, zoom: float,
                      box_w_px: float = 200.0) -> tuple[float, float]:
    """메모 내용에 맞는 상자 크기를 PDF 포인트로 반환 (자동 높이).
    미리보기(QGraphicsTextItem)와 동일한 QTextDocument·줄바꿈으로 계산해
    글자가 상자 밖으로 삐져나오지 않게 한다 (한글 연속 문자도 강제 줄바꿈)."""
    from PySide6.QtGui import QFont, QTextDocument, QTextOption
    z = max(1e-6, zoom)
    f = QFont(family or _DEFAULT_FAMILY)
    f.setPixelSize(max(9, int(fontsize * z)))
    text_w_px = max(20.0, box_w_px - 16)
    doc = QTextDocument()
    doc.setDefaultFont(f)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    doc.setDefaultTextOption(opt)
    doc.setTextWidth(text_w_px)
    doc.setPlainText(text or ' ')
    h_px = max(44.0, doc.size().height() + 14)
    return box_w_px / z, h_px / z


class _NoteInsertDialog(QDialog):
    def __init__(self, parent=None, initial_text: str = '',
                 initial_family: str = '', initial_size: int = 0,
                 initial_opacity: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle('메모 수정' if initial_text else '메모 입력')
        self.setMinimumWidth(400)
        self._initial_family = initial_family or _DEFAULT_FAMILY
        self._initial_size = initial_size or _DEFAULT_SIZE
        self._initial_text = initial_text

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ── 글꼴 선택 ──────────────────────────────────────────
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel('글꼴'))
        self._font_cb = FontPickerCombo()
        self._font_cb.setCurrentFont(QFont(self._initial_family))
        self._font_cb.currentFontChanged.connect(self._on_font_changed)
        font_row.addWidget(self._font_cb, 1)
        font_row.addWidget(QLabel('크기'))
        self._size_sb = QSpinBox()
        self._size_sb.setRange(4, 200)
        self._size_sb.setValue(self._initial_size)
        self._size_sb.valueChanged.connect(self._on_font_changed)
        font_row.addWidget(self._size_sb)
        font_row.addWidget(QLabel('pt'))
        lay.addLayout(font_row)

        # ── 투명도 ─────────────────────────────────────────────
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel('투명도'))
        self._op_slider = QSlider(Qt.Orientation.Horizontal)
        self._op_slider.setRange(10, 100)
        self._op_slider.setValue(int(round(max(0.1, initial_opacity) * 100)))
        op_row.addWidget(self._op_slider, 1)
        self._op_lbl = QLabel(f'{self._op_slider.value()}%')
        self._op_lbl.setMinimumWidth(42)
        op_row.addWidget(self._op_lbl)
        self._op_slider.valueChanged.connect(
            lambda v: self._op_lbl.setText(f'{v}%'))
        lay.addLayout(op_row)

        # 선택된 글꼴 미리보기
        self._preview_lbl = QLabel()
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet(
            'padding: 5px 10px; background: #fff8e1; border: 2px solid #ffa000;'
            'border-radius: 6px; color: #e65100;')
        self._preview_lbl.setFixedHeight(36)
        lay.addWidget(self._preview_lbl)

        # ── 텍스트 입력 ─────────────────────────────────────────
        lay.addWidget(QLabel('메모 내용'))
        self._edit = QTextEdit()
        self._edit.setMinimumHeight(100)
        if self._initial_text:
            self._edit.setPlainText(self._initial_text)
        lay.addWidget(self._edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._on_font_changed()

    def _on_font_changed(self):
        family = self._font_cb.currentFont().family()
        size   = self._size_sb.value()
        self._preview_lbl.setText(f'선택된 글꼴: {family}  |  {size}pt')
        f = QFont(family, 11)
        f.setBold(True)
        self._preview_lbl.setFont(f)
        ef = QFont(family, size)
        self._edit.setFont(ef)

    def text(self) -> str:
        return self._edit.toPlainText()

    def font_family(self) -> str:
        return self._font_cb.currentFont().family()

    def font_size(self) -> int:
        return self._size_sb.value()

    def opacity(self) -> float:
        return self._op_slider.value() / 100.0


class NoteTool(BaseTool):
    name     = 'note'
    label    = '📌 메모'
    cursor   = Qt.CursorShape.PointingHandCursor
    shortcut = 'N'

    def __init__(self):
        # 기존 메모/어노테이션 클릭 시 선택·이동·크기조절 위임
        self._delegate = ExistingSelectionDelegate()

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def deactivate(self, view):
        super().deactivate(view)
        self._delegate.deactivate(view)

    def on_press(self, pos, event, view):
        if event.button() == Qt.MouseButton.LeftButton:
            self._delegate.press(pos, event, view)

    def on_move(self, pos, event, view):
        self._delegate.move(pos, event, view)

    def on_key(self, event, view) -> bool:
        return self._delegate.key(event, view)

    def on_double_click(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        # 미확정 메모는 전용 다이얼로그(글꼴 포함)로 편집
        pending = self._delegate.find_pending_at(pos, view)
        if pending is not None and pending.annot_type == 'text':
            dlg = _NoteInsertDialog(view, initial_text=pending.text,
                                    initial_family=pending.fontname,
                                    initial_size=int(pending.fontsize),
                                    initial_opacity=getattr(pending, 'opacity', 1.0))
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return True
            text = dlg.text().strip()
            if not text:
                pending.remove_from_scene()
                view.pending_layer().remove_uid(pending.uid)
                self._delegate.deactivate(view)
                view.setDragMode(view.DragMode.NoDrag)
                view.notify_pending_changed()
                return True
            pending.text = text
            pending.fontname = dlg.font_family()
            pending.fontsize = float(dlg.font_size())
            pending.opacity = dlg.opacity()
            # 내용 변경에 맞춰 상자 높이 재계산 (기존 폭 유지, 좌상단 고정)
            r = pending.fitz_rect
            cur_w_px = max(120.0, r.width * view.zoom())
            w_pt, h_pt = measure_note_rect(text, pending.fontname,
                                           pending.fontsize, view.zoom(), cur_w_px)
            pending.fitz_rect = fitz.Rect(r.x0, r.y0, r.x0 + w_pt, r.y0 + h_pt)
            view.rebuild_pending_item(pending)
            view.doc().mark_dirty()
            self._delegate.refresh_selection_box(pending, view)
            return True
        return self._delegate.double_click(pos, event, view)

    def on_release(self, pos: QPointF, event: QMouseEvent, view):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not view.doc().is_open:
            return
        if self._delegate.release(pos, event, view):
            return   # 기존 어노테이션 조작이었음 — 새 메모 만들지 않음

        dlg = _NoteInsertDialog(view)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.text().strip()
        if not text:
            return

        family   = dlg.font_family()
        fontsize = dlg.font_size()
        opacity  = dlg.opacity()

        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        # 내용에 맞춰 상자 높이 자동 계산
        w_pt, h_pt = measure_note_rect(text, family, float(fontsize), view.zoom())
        rect = fitz.Rect(fitz_pt.x, fitz_pt.y, fitz_pt.x + w_pt, fitz_pt.y + h_pt)

        pa = PendingAnnotation(
            uid        = view.pending_layer().next_uid(),
            page_index = page_idx,
            tool_name  = self.name,
            annot_type = 'text',
            fitz_rect  = rect,
            text       = text,
            fontname   = family,
            fontsize   = float(fontsize),
            opacity    = opacity,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()

        # 캔버스 미리보기 — 공용 포스트잇 렌더러 사용
        from ui.canvas_view import _make_pending_item
        item = _make_pending_item(pa, view.page_offset(page_idx), view.zoom())
        if item is not None:
            item.setZValue(20)
            view.scene().addItem(item)
            pa.q_item = item

        view.notify_pending_changed()
