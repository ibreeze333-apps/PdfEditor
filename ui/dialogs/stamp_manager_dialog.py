from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from utils.errlog import swallowed

CUSTOM_STAMPS_DIR  = Path.home() / '.pdf_editor' / 'custom_stamps'
CUSTOM_STAMPS_JSON = CUSTOM_STAMPS_DIR / 'stamps.json'

# 도장 모양 (id, 이름, 아이콘)
_SEAL_SHAPES = [
    ('rect',          '직사각형',   '▭'),
    ('square',        '정사각형',   '□'),
    ('double_square', '이중 사각',  '⊡'),
    ('circle',        '원형',       '○'),
    ('double_circle', '이중 원형',  '◎'),
    ('oval',          '타원형',     '⬭'),
    ('hexagon',       '육각형',     '⬡'),
    ('diamond',       '마름모',     '◇'),
    ('postage',       '우표형',     '⊠'),
    ('star_circle',   '별장식 원형', '✦'),
    ('badge',         '배지형',     '⬒'),
]
_SHAPE_LABELS = {sid: lbl for sid, lbl, _ in _SEAL_SHAPES}


def load_custom_stamps() -> list:
    if not CUSTOM_STAMPS_JSON.exists():
        return []
    try:
        return json.loads(CUSTOM_STAMPS_JSON.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_custom_stamps(stamps: list):
    CUSTOM_STAMPS_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_STAMPS_JSON.write_text(
        json.dumps(stamps, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


# ──────────────────────────────────────────────────────────────────────────────
# 모양 선택 위젯
# ──────────────────────────────────────────────────────────────────────────────

class _ShapeBtn(QPushButton):
    """도장 모양 선택 버튼 — 아이콘 + 이름."""

    def __init__(self, shape_id: str, label: str, icon: str, parent=None):
        super().__init__(parent)
        self._shape_id = shape_id
        self.setText(f'{icon}\n{label}')
        self.setCheckable(True)
        self.setFixedSize(74, 58)
        self.setStyleSheet(
            'QPushButton {'
            '  border: 1px solid #bbb; border-radius: 5px;'
            '  font-size: 10px; padding: 2px;'
            '}'
            'QPushButton:checked {'
            '  background: #ddeeff; border: 2px solid #2255bb;'
            '  font-weight: bold;'
            '}'
            'QPushButton:hover { background: #f0f4ff; }'
        )

    @property
    def shape_id(self) -> str:
        return self._shape_id


_COLS = 6   # 한 줄에 몇 개


class SealShapeSelector(QWidget):
    """도장 모양 11종 선택 위젯 (그리드)."""

    shape_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self._btns: dict[str, _ShapeBtn] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for idx, (sid, lbl, icon) in enumerate(_SEAL_SHAPES):
            row, col = divmod(idx, _COLS)
            btn = _ShapeBtn(sid, lbl, icon)
            self._group.addButton(btn)
            self._btns[sid] = btn
            btn.clicked.connect(lambda chk=False, s=sid: self.shape_changed.emit(s))
            lay.addWidget(btn, row, col)

        self._btns['rect'].setChecked(True)

    def selected_shape(self) -> str:
        for sid, btn in self._btns.items():
            if btn.isChecked():
                return sid
        return 'rect'

    def set_shape(self, shape_id: str):
        if shape_id in self._btns:
            self._btns[shape_id].setChecked(True)


# ──────────────────────────────────────────────────────────────────────────────
# 도장 만들기 다이얼로그
# ──────────────────────────────────────────────────────────────────────────────

class StampCreatorDialog(QDialog):
    """텍스트 도장 만들기 — 모양·색상·폰트·미리보기 포함."""

    def __init__(self, init_data: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('도장 스탬프 만들기')
        self.setMinimumWidth(520)
        self.result_stamp: dict | None = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ── 텍스트 / 이름 ────────────────────────────────────────
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText('예: 홍길동  또는  주식회사\\n한빛미디어  (줄바꿈: \\n)')
        form.addRow('텍스트:', self._text_edit)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('스탬프 목록에 표시될 이름')
        form.addRow('이름:', self._name_edit)
        lay.addLayout(form)

        # ── 도장 모양 ────────────────────────────────────────────
        lay.addWidget(QLabel('도장 모양:'))
        self._shape_sel = SealShapeSelector()
        lay.addWidget(self._shape_sel)

        # ── 색상 + 폰트 ──────────────────────────────────────────
        opt_row = QHBoxLayout()
        self._color = QColor(180, 0, 0)
        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(130)
        self._color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()
        opt_row.addWidget(QLabel('색상:'))
        opt_row.addWidget(self._color_btn)
        opt_row.addSpacing(16)

        self._font = QFont('Malgun Gothic', 18)
        self._font_btn = QPushButton('글꼴 선택')
        self._font_btn.setFixedWidth(110)
        self._font_btn.clicked.connect(self._pick_font)
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 96)
        self._font_size_spin.setValue(18)
        self._font_size_spin.setFixedWidth(58)
        opt_row.addWidget(QLabel('폰트:'))
        opt_row.addWidget(self._font_btn)
        opt_row.addWidget(QLabel('크기:'))
        opt_row.addWidget(self._font_size_spin)
        opt_row.addStretch()
        lay.addLayout(opt_row)

        # ── 미리보기 ─────────────────────────────────────────────
        self._preview_lbl = QLabel('미리보기')
        self._preview_lbl.setFixedSize(240, 120)
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setStyleSheet(
            'QLabel { border: 1px solid #ccc; background: #f9f9f9;'
            '  border-radius: 4px; color: #888; font-size: 11px; }'
        )
        prev_row = QHBoxLayout()
        prev_row.addStretch()
        prev_row.addWidget(self._preview_lbl)
        prev_row.addStretch()
        lay.addLayout(prev_row)

        # ── 버튼 ────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        # ── 초기값 채우기 ────────────────────────────────────────
        if init_data:
            self._text_edit.setText(init_data.get('text', ''))
            self._name_edit.setText(init_data.get('name', ''))
            c = init_data.get('color', [0.7, 0.0, 0.0])
            self._color = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
            self._update_color_btn()
            self._shape_sel.set_shape(init_data.get('shape', 'rect'))
            fam  = init_data.get('font_family', 'Malgun Gothic')
            size = int(init_data.get('font_size', 18) or 18)
            self._font = QFont(fam, size)
            self._font_size_spin.setValue(size)

        # 신호 연결 (초기화 후에)
        self._text_edit.textChanged.connect(self._update_preview)
        self._shape_sel.shape_changed.connect(self._update_preview)
        self._font_size_spin.valueChanged.connect(self._update_preview)

        self._update_preview()

    # ── helpers ─────────────────────────────────────────────────

    def _update_color_btn(self):
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        fg = 'white' if (r + g + b) < 400 else '#333'
        self._color_btn.setStyleSheet(
            f'QPushButton {{ background: rgb({r},{g},{b}); color: {fg};'
            f' border: 1px solid #888; border-radius: 3px; }}'
        )
        self._color_btn.setText(f'#{r:02x}{g:02x}{b:02x}')

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, '도장 색상')
        if c.isValid():
            self._color = c
            self._update_color_btn()
            self._update_preview()

    def _pick_font(self):
        ok, f = QFontDialog.getFont(self._font, self)
        if ok:
            self._font = f
            if f.pointSize() > 0:
                self._font_size_spin.setValue(f.pointSize())
            self._update_preview()

    def _update_preview(self):
        try:
            from tools.stamp_tool import _build_stamp_image, _stamp_style
            text  = self._text_edit.text() or '도장'
            # \n 리터럴을 실제 줄바꿈으로
            text  = text.replace('\\n', '\n')
            shape = self._shape_sel.selected_shape()
            r, g, b = self._color.red(), self._color.green(), self._color.blue()
            color_hex  = f'#{r:02x}{g:02x}{b:02x}'
            font_size  = self._font_size_spin.value()
            font_family = self._font.family()
            _, inner_color = _stamp_style(text)

            _sq = ('square', 'double_square', 'circle', 'double_circle',
                   'hexagon', 'diamond', 'star_circle', 'badge')
            char_count = max(len(text.replace('\n', '')), 2)
            if shape in _sq:
                side = max(80, int(char_count * font_size * 1.0) + 30)
                pw, ph = side, side
            elif shape == 'oval':
                pw = max(120, int(char_count * font_size * 1.1) + 30)
                ph = max(55, int(font_size * 1.3) + 20)
            else:
                pw = max(120, int(char_count * font_size * 1.2) + 30)
                ph = max(50, int(font_size * 1.4) + 20)

            path = _build_stamp_image(
                text, pw, ph, color_hex, inner_color,
                preferred_family=font_family,
                preferred_size=font_size,
                shape=shape,
                uppercase=False,
            )
            pxm = QPixmap(path)
            if not pxm.isNull():
                pxm = pxm.scaled(
                    230, 112,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_lbl.setPixmap(pxm)
            else:
                self._preview_lbl.setText('미리보기 없음')
        except Exception as e:
            self._preview_lbl.setText(f'오류\n{e}')

    def _accept(self):
        text = self._text_edit.text().strip()
        name = self._name_edit.text().strip() or text
        if not text:
            QMessageBox.warning(self, '입력 오류', '텍스트를 입력하세요.')
            return
        if not name:
            QMessageBox.warning(self, '입력 오류', '스탬프 이름을 입력하세요.')
            return
        c = self._color
        # \n 리터럴을 실제 줄바꿈으로 저장
        self.result_stamp = {
            'type':        'text',
            'name':        name,
            'text':        text.replace('\\n', '\n'),
            'color':       [c.redF(), c.greenF(), c.blueF()],
            'font_family': self._font.family(),
            'font_size':   self._font_size_spin.value(),
            'shape':       self._shape_sel.selected_shape(),
        }
        self.accept()


# ──────────────────────────────────────────────────────────────────────────────
# 스탬프 관리 다이얼로그
# ──────────────────────────────────────────────────────────────────────────────

class StampManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('커스텀 스탬프 관리')
        self.setMinimumWidth(500)
        self.setMinimumHeight(380)
        self._stamps: list = load_custom_stamps()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('등록된 커스텀 스탬프 목록:'))

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._add_img_btn  = QPushButton('📷 이미지 스탬프 추가')
        self._add_txt_btn  = QPushButton('🖋 도장 스탬프 만들기')
        self._edit_btn     = QPushButton('✏ 편집')
        self._del_btn      = QPushButton('🗑 삭제')
        self._edit_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        btn_row.addWidget(self._add_img_btn)
        btn_row.addWidget(self._add_txt_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._del_btn)
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        layout.addWidget(btns)

        self._add_img_btn.clicked.connect(self._add_image)
        self._add_txt_btn.clicked.connect(self._add_text)
        self._edit_btn.clicked.connect(self._edit_selected)
        self._del_btn.clicked.connect(self._delete_selected)
        self._list.currentRowChanged.connect(self._on_row_changed)

        self._refresh_list()

    def _on_row_changed(self, row: int):
        has_sel = row >= 0
        self._del_btn.setEnabled(has_sel)
        # 편집은 텍스트 스탬프만 가능
        if has_sel and row < len(self._stamps):
            self._edit_btn.setEnabled(self._stamps[row].get('type') == 'text')
        else:
            self._edit_btn.setEnabled(False)

    def _refresh_list(self):
        self._list.clear()
        for stamp in self._stamps:
            stype = stamp.get('type', 'text')
            if stype == 'image':
                icon = '📷'
                info = stamp.get('path', '')
            else:
                shape = stamp.get('shape', 'rect')
                icon  = '🖋'
                info  = f"[{_SHAPE_LABELS.get(shape, shape)}]  {stamp.get('text', '')}"
            name = stamp.get('name', '(이름 없음)')
            item = QListWidgetItem(f'{icon}  {name}   {info}')
            item.setToolTip(info)
            self._list.addItem(item)

    def _add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '스탬프 이미지 선택', '',
            '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp)',
        )
        if not path:
            return
        name, ok = QInputDialog.getText(
            self, '스탬프 이름', '스탬프 이름을 입력하세요:', text=Path(path).stem,
        )
        if not ok or not name.strip():
            return
        CUSTOM_STAMPS_DIR.mkdir(parents=True, exist_ok=True)
        dst = CUSTOM_STAMPS_DIR / Path(path).name
        try:
            shutil.copy2(path, dst)
        except Exception as exc:
            QMessageBox.warning(self, '오류', f'이미지 복사 실패:\n{exc}')
            return
        self._stamps.append({'type': 'image', 'name': name.strip(), 'path': str(dst)})
        save_custom_stamps(self._stamps)
        self._refresh_list()

    def _add_text(self):
        dlg = StampCreatorDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_stamp:
            self._stamps.append(dlg.result_stamp)
            save_custom_stamps(self._stamps)
            self._refresh_list()

    def _edit_selected(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._stamps):
            return
        stamp = self._stamps[row]
        if stamp.get('type') != 'text':
            return
        dlg = StampCreatorDialog(init_data=stamp, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_stamp:
            self._stamps[row] = dlg.result_stamp
            save_custom_stamps(self._stamps)
            self._refresh_list()

    def _delete_selected(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._stamps):
            return
        stamp = self._stamps[row]
        if QMessageBox.question(
            self, '삭제 확인',
            f'스탬프 "{stamp.get("name")}"을 삭제하시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if stamp.get('type') == 'image':
            path = Path(stamp.get('path', ''))
            if path.exists():
                if QMessageBox.question(
                    self, '파일 삭제', f'이미지 파일도 삭제할까요?\n{path}',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                ) == QMessageBox.StandardButton.Yes:
                    try:
                        path.unlink()
                    except Exception:
                        swallowed()
        self._stamps.pop(row)
        save_custom_stamps(self._stamps)
        self._refresh_list()
