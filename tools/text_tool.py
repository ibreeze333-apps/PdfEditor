from __future__ import annotations

import hashlib
import os
import fitz

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QMouseEvent, QPen, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QDialogButtonBox,
    QFontComboBox,
    QSpinBox,
    QFontDialog,
)

from tools.base_tool import BaseTool
from tools.select_tool import ExistingSelectionDelegate
from utils.annot_mapper import resolve_page_and_fitz_pt
from utils.pending_layer import PendingAnnotation

try:
    import winreg
except ImportError:  # pragma: no cover - Windows app fallback
    winreg = None


_FONT_REGISTRY_CACHE: dict[str, list[tuple[str, str]]] | None = None
_BUILTIN_PDF_FONT_MAP = {
    'arial': 'helv',
    'helvetica': 'helv',
    'timesnewroman': 'Times-Roman',
    'timesroman': 'Times-Roman',
    'timesnewromanpsmt': 'Times-Roman',
    'couriernew': 'cour',
    'courier': 'cour',
}


def _normalize_font_key(name: str) -> str:
    return ''.join(ch.lower() for ch in name if ch.isalnum())


def _pdf_font_alias(source: str) -> str:
    digest = hashlib.md5(source.encode('utf-8')).hexdigest().upper()
    return f'F{digest[:3]}'


def _load_windows_font_registry() -> dict[str, list[tuple[str, str]]]:
    global _FONT_REGISTRY_CACHE
    if _FONT_REGISTRY_CACHE is not None:
        return _FONT_REGISTRY_CACHE

    font_dir = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    mapping: dict[str, list[tuple[str, str]]] = {}
    if winreg is None:
        _FONT_REGISTRY_CACHE = mapping
        return mapping

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts',
        )
    except OSError:
        _FONT_REGISTRY_CACHE = mapping
        return mapping

    index = 0
    while True:
        try:
            display_name, file_name, _ = winreg.EnumValue(key, index)
        except OSError:
            break
        index += 1
        if not isinstance(file_name, str):
            continue
        path = file_name if os.path.isabs(file_name) else os.path.join(font_dir, file_name)
        if not os.path.exists(path):
            continue

        clean_name = display_name.split('(')[0].strip()
        candidates = {
            clean_name,
            os.path.splitext(os.path.basename(path))[0],
        }
        for candidate in candidates:
            norm = _normalize_font_key(candidate)
            if norm:
                mapping.setdefault(norm, []).append((clean_name, path))

    _FONT_REGISTRY_CACHE = mapping
    return mapping


def _pick_font_path(entries: list[tuple[str, str]]) -> str:
    def score(item: tuple[str, str]) -> tuple[int, str]:
        label = f'{item[0]} {os.path.basename(item[1])}'.lower()
        penalty = sum(token in label for token in ('bold', 'italic', 'oblique', 'black', 'light'))
        return penalty, label

    return sorted(entries, key=score)[0][1]


def _resolve_font_target(family: str) -> tuple[str, str]:
    built_in = _BUILTIN_PDF_FONT_MAP.get(_normalize_font_key(family))
    if built_in:
        return '', built_in

    mapping = _load_windows_font_registry()
    norm_family = _normalize_font_key(family)
    entries = list(mapping.get(norm_family, []))
    if not entries:
        for key, value in mapping.items():
            if norm_family and (norm_family in key or key in norm_family):
                entries.extend(value)
    if entries:
        path = _pick_font_path(entries)
        return path, _pdf_font_alias(path)
    return '', 'helv'


class _TextInsertDialog(QDialog):
    def __init__(self, default_family: str, default_size: int, parent=None,
                 initial_text: str = ''):
        super().__init__(parent)
        self.setWindowTitle('텍스트 수정' if initial_text else '텍스트 삽입')
        self.setMinimumWidth(420)
        self._initial_text = initial_text

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel('글꼴'))
        from ui.font_combo import FontPickerCombo
        self._font_cb = FontPickerCombo()
        self._font_cb.setCurrentFont(QFont(default_family))
        self._font_cb.currentFontChanged.connect(lambda _font: self._update_preview_font())
        font_row.addWidget(self._font_cb, 1)
        font_row.addWidget(QLabel('크기'))
        self._size_sb = QSpinBox()
        self._size_sb.setRange(4, 300)
        self._size_sb.setValue(max(4, int(default_size)))
        self._size_sb.valueChanged.connect(lambda _value: self._update_preview_font())
        font_row.addWidget(self._size_sb)
        font_row.addWidget(QLabel('pt'))
        lay.addLayout(font_row)

        # 선택된 글꼴 미리보기
        self._font_preview_lbl = QLabel()
        self._font_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._font_preview_lbl.setStyleSheet(
            'padding: 5px 10px; background: #f0f4ff; border: 2px solid #4361ee;'
            'border-radius: 6px; color: #1a237e;')
        self._font_preview_lbl.setFixedHeight(36)
        lay.addWidget(self._font_preview_lbl)
        self._refresh_font_preview()

        lay.addWidget(QLabel('입력할 텍스트'))
        self._edit = QTextEdit()
        self._edit.setMinimumHeight(110)
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

        self._update_preview_font()

    def _refresh_font_preview(self):
        family = self._font_cb.currentFont().family()
        size   = self._size_sb.value()
        self._font_preview_lbl.setText(f'선택된 글꼴: {family}  |  {size}pt')
        f = QFont(family, 11)
        f.setBold(True)
        self._font_preview_lbl.setFont(f)

    def _update_preview_font(self):
        font = self._font_cb.currentFont()
        font.setPointSize(self._size_sb.value())
        self._edit.setFont(font)
        self._refresh_font_preview()

    def text(self) -> str:
        return self._edit.toPlainText()

    def font_family(self) -> str:
        return self._font_cb.currentFont().family()

    def font_size(self) -> int:
        return self._size_sb.value()

    def font_option(self) -> tuple[str, str, str]:
        family = self.font_family()
        fontfile, fontname = _resolve_font_target(family)
        return fontfile, fontname, family


class TextTool(BaseTool):
    name = 'text'
    label = '\U0001f524 \ud14d\uc2a4\ud2b8'
    cursor = Qt.CursorShape.IBeamCursor
    shortcut = 'T'

    def __init__(self):
        self._font_size: int = 12
        self._font_family: str = 'Malgun Gothic'
        # 기존 텍스트/어노테이션 클릭 시 선택·이동·크기조절 위임
        self._delegate = ExistingSelectionDelegate()

    def activate(self, view):
        super().activate(view)
        view.setDragMode(view.DragMode.NoDrag)

    def deactivate(self, view):
        super().deactivate(view)
        self._delegate.deactivate(view)

    def configure_style(self, parent=None):
        font = QFont(self._font_family, max(1, int(self._font_size)))
        ok, selected = QFontDialog.getFont(font, parent, '\ud14d\uc2a4\ud2b8 \uae00\uaf34')
        if ok:
            self._font_family = selected.family()
            size = selected.pointSize()
            if size > 0:
                self._font_size = size
    def on_press(self, pos, event, view):
        if event.button() == Qt.MouseButton.LeftButton:
            self._delegate.press(pos, event, view)

    def on_move(self, pos, event, view):
        self._delegate.move(pos, event, view)

    def on_key(self, event, view) -> bool:
        return self._delegate.key(event, view)

    def on_double_click(self, pos: QPointF, event: QMouseEvent, view) -> bool:
        # 미확정 텍스트는 전용 다이얼로그(글꼴 포함)로 편집
        pending = self._delegate.find_pending_at(pos, view)
        if pending is not None and pending.annot_type == 'direct_text':
            dlg = _TextInsertDialog(self._font_family, int(pending.fontsize), view,
                                    initial_text=pending.text)
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
            fontfile, fontname, qt_family = dlg.font_option()
            fs = dlg.font_size()
            pending.text = text
            pending.fontsize = float(fs)
            pending.fontname = fontname
            pending.fontfile = fontfile
            # 내용에 맞춰 상자 크기 재계산 (좌상단 고정)
            lines = text.splitlines() or ['']
            longest = max(len(line) for line in lines)
            w = max(180, longest * fs * 0.62 + 12)
            h = max(fs + 8, len(lines) * (fs + 4) + 8)
            r = pending.fitz_rect
            pending.fitz_rect = fitz.Rect(r.x0, r.y0, r.x0 + w, r.y0 + h)
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
            return   # 기존 어노테이션 조작이었음 — 새 텍스트 만들지 않음

        dlg = _TextInsertDialog(self._font_family, self._font_size, view)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        text = dlg.text().strip()
        if not text:
            return

        fontfile, fontname, qt_family = dlg.font_option()
        fs = dlg.font_size()
        self._font_family = qt_family
        self._font_size = fs

        page_idx, fitz_pt = resolve_page_and_fitz_pt(view, pos)
        lines = text.splitlines() or ['']
        longest = max(len(line) for line in lines)
        w = max(180, longest * fs * 0.62 + 12)
        h = max(fs + 8, len(lines) * (fs + 4) + 8)
        rect = fitz.Rect(fitz_pt.x, fitz_pt.y, fitz_pt.x + w, fitz_pt.y + h)

        pa = PendingAnnotation(
            uid=view.pending_layer().next_uid(),
            page_index=page_idx,
            tool_name=self.name,
            annot_type='direct_text',
            fitz_rect=rect,
            text=text,
            fontsize=float(fs),
            fontname=fontname,
            fontfile=fontfile,
            text_color=(0.0, 0.0, 0.0),
            text_align=fitz.TEXT_ALIGN_LEFT,
        )
        view.pending_layer().add(pa)
        view.doc().mark_dirty()

        # 캔버스 미리보기 — 공용 렌더러 사용 (점선 없이 실제 텍스트처럼)
        from ui.canvas_view import _make_pending_item
        item = _make_pending_item(pa, view.page_offset(page_idx), view.zoom())
        if item is not None:
            item.setZValue(20)
            view.scene().addItem(item)
            pa.q_item = item

        view.notify_pending_changed()
