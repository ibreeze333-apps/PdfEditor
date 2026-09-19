# ui/dialogs/security_dialog.py — 보안 기능 다이얼로그 모음
# 문서 암호/권한, 개인정보 교정(redaction), 전자 서명(이미지/텍스트)
from __future__ import annotations
import re
import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QCheckBox, QComboBox, QSpinBox, QPlainTextEdit, QDialogButtonBox,
    QPushButton, QFileDialog, QGroupBox, QRadioButton, QWidget,
)
from utils.errlog import swallowed


# ════════════════════════════════════════════════════════════════════
# 1) 암호 / 권한 설정
# ════════════════════════════════════════════════════════════════════
class EncryptDialog(QDialog):
    """문서 열람 암호(User) + 관리자 암호(Owner) + 열람자 권한."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('🔒 문서 암호 / 권한 설정')
        self.setMinimumWidth(440)
        ly = QVBoxLayout(self)

        info = QLabel('설정한 암호로 암호화된 <b>사본</b>을 새로 저장합니다. '
                      '원본 파일은 그대로 유지됩니다.')
        info.setWordWrap(True)
        info.setStyleSheet('color:#444;')
        ly.addWidget(info)

        pw_box = QGroupBox('암호')
        pw_ly = QGridLayout(pw_box)

        pw_ly.addWidget(QLabel('<b>열람 암호</b>'), 0, 0)
        self._user_ed = QLineEdit(); self._user_ed.setEchoMode(QLineEdit.EchoMode.Password)
        self._user_ed.setPlaceholderText('문서를 열 때 필요 (비우면 없음)')
        pw_ly.addWidget(self._user_ed, 0, 1)
        user_hint = QLabel('문서를 받는 사람에게 알려 줄 암호입니다. '
                           '이 암호로 열면 아래에서 체크한 것만 할 수 있습니다.')
        user_hint.setStyleSheet('color:#666; font-size:11px;')
        user_hint.setWordWrap(True)
        pw_ly.addWidget(user_hint, 1, 1)

        pw_ly.addWidget(QLabel('<b>관리자 암호</b>'), 2, 0)
        self._owner_ed = QLineEdit(); self._owner_ed.setEchoMode(QLineEdit.EchoMode.Password)
        self._owner_ed.setPlaceholderText('제한을 풀 때 필요 (비우면 없음)')
        pw_ly.addWidget(self._owner_ed, 2, 1)
        owner_hint = QLabel('<b>나만 갖고 있는 암호</b>입니다. 이 암호로 열면 '
                            '제한 없이 <b>모든 작업</b>을 할 수 있습니다. '
                            '남에게 알려 주면 제한이 의미가 없어집니다.')
        owner_hint.setStyleSheet('color:#666; font-size:11px;')
        owner_hint.setWordWrap(True)
        pw_ly.addWidget(owner_hint, 3, 1)

        self._show_cb = QCheckBox('암호 표시')
        self._show_cb.toggled.connect(self._toggle_echo)
        pw_ly.addWidget(self._show_cb, 4, 1)
        ly.addWidget(pw_box)

        perm_box = QGroupBox('열람자에게 허용할 권한 (체크한 작업만 허용)')
        pl = QGridLayout(perm_box)
        self._perm_print = QCheckBox('인쇄'); self._perm_print.setChecked(True)
        self._perm_copy = QCheckBox('텍스트/이미지 복사'); self._perm_copy.setChecked(True)
        self._perm_modify = QCheckBox('문서 편집'); self._perm_modify.setChecked(True)
        self._perm_annot = QCheckBox('주석 추가'); self._perm_annot.setChecked(True)
        self._perm_form = QCheckBox('양식 입력'); self._perm_form.setChecked(True)
        self._perm_assemble = QCheckBox('페이지 편집(삽입/삭제/회전)'); self._perm_assemble.setChecked(True)
        for i, cb in enumerate((self._perm_print, self._perm_copy, self._perm_modify,
                                self._perm_annot, self._perm_form, self._perm_assemble)):
            pl.addWidget(cb, i // 2, i % 2)
        note = QLabel('여기서 체크한 제한은 <b>열람 암호로 연 사람에게만</b> 적용됩니다. '
                      '관리자 암호로 열면 제한 없이 모든 작업이 가능합니다.<br>'
                      '※ 제한을 걸려면 <b>관리자 암호를 반드시 설정</b>하고, '
                      '받는 사람에게는 <b>열람 암호만</b> 알려 주세요. '
                      '두 암호는 서로 달라야 합니다.')
        note.setStyleSheet('color:#888; font-size:12px;')
        note.setWordWrap(True)
        pl.addWidget(note, 3, 0, 1, 2)
        ly.addWidget(perm_box)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('암호화 사본 저장…')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    def _toggle_echo(self, on: bool):
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self._user_ed.setEchoMode(mode)
        self._owner_ed.setEchoMode(mode)

    def user_pw(self) -> str:
        return self._user_ed.text()

    def owner_pw(self) -> str:
        return self._owner_ed.text()

    def permissions(self) -> int:
        perm = int(fitz.PDF_PERM_ACCESSIBILITY)   # 접근성은 항상 허용
        if self._perm_print.isChecked():
            perm |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
        if self._perm_copy.isChecked():
            perm |= fitz.PDF_PERM_COPY
        if self._perm_modify.isChecked():
            perm |= fitz.PDF_PERM_MODIFY
        if self._perm_annot.isChecked():
            perm |= fitz.PDF_PERM_ANNOTATE
        if self._perm_form.isChecked():
            perm |= fitz.PDF_PERM_FORM
        if self._perm_assemble.isChecked():
            perm |= fitz.PDF_PERM_ASSEMBLE
        return perm

    @staticmethod
    def all_permissions() -> int:
        """모든 권한을 허용하는 비트마스크 — '제한 없음' 판정 기준."""
        return (int(fitz.PDF_PERM_ACCESSIBILITY)
                | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
                | fitz.PDF_PERM_COPY | fitz.PDF_PERM_MODIFY
                | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
                | fitz.PDF_PERM_ASSEMBLE)


# ════════════════════════════════════════════════════════════════════
# 2) 개인정보 교정 (Redaction)
# ════════════════════════════════════════════════════════════════════
# 자주 쓰는 개인정보 정규식 프리셋
REDACT_PRESETS = [
    ('주민등록번호', r'\d{6}\s*-\s*\d{7}'),
    ('전화번호', r'01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}'),
    ('이메일', r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
    ('카드번호', r'\d{4}\s*-?\s*\d{4}\s*-?\s*\d{4}\s*-?\s*\d{4}'),
    ('계좌번호(숫자 10자리 이상)', r'\d{2,6}-\d{2,6}-\d{2,7}'),
]


class RedactDialog(QDialog):
    """민감정보를 검색해 영구 삭제(교정)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('🖊 개인정보 교정 (Redaction)')
        self.setMinimumWidth(460)
        ly = QVBoxLayout(self)

        warn = QLabel('⚠ 교정은 <b>되돌릴 수 없습니다</b>. 해당 영역의 글자·이미지가 '
                      '문서에서 영구히 삭제되고 검게 칠해집니다. 원본을 보관한 뒤 진행하세요.')
        warn.setWordWrap(True)
        warn.setStyleSheet('color:#b00; background:#fff4f4; padding:6px; border-radius:4px;')
        ly.addWidget(warn)

        preset_box = QGroupBox('자동 검색 (개인정보 유형)')
        pl = QVBoxLayout(preset_box)
        self._preset_cbs = []
        for label, pattern in REDACT_PRESETS:
            cb = QCheckBox(label)
            self._preset_cbs.append((cb, pattern))
            pl.addWidget(cb)
        ly.addWidget(preset_box)

        ly.addWidget(QLabel('직접 지정할 단어/문구 (한 줄에 하나)'))
        self._custom_ed = QPlainTextEdit()
        self._custom_ed.setPlaceholderText('예)\n홍길동\n서울시 강남구 …')
        self._custom_ed.setFixedHeight(90)
        ly.addWidget(self._custom_ed)

        opt = QHBoxLayout()
        opt.addWidget(QLabel('범위:'))
        self._range_cb = QComboBox()
        self._range_cb.addItems(['전체 페이지', '현재 페이지'])
        opt.addWidget(self._range_cb)
        opt.addStretch(1)
        self._label_cb = QCheckBox('교정 위에 "삭제됨" 표시')
        opt.addWidget(self._label_cb)
        ly.addLayout(opt)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('검색 후 교정 실행')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    def patterns(self) -> list[str]:
        return [pat for cb, pat in self._preset_cbs if cb.isChecked()]

    def literals(self) -> list[str]:
        return [ln.strip() for ln in self._custom_ed.toPlainText().splitlines() if ln.strip()]

    def all_pages(self) -> bool:
        return self._range_cb.currentIndex() == 0

    def show_label(self) -> bool:
        return self._label_cb.isChecked()

    # ── 교정 실행 (정적) ──────────────────────────────────────────────
    @staticmethod
    def collect_rects(page, patterns: list[str], literals: list[str]) -> list[fitz.Rect]:
        rects: list[fitz.Rect] = []
        # 직접 지정 문구: 그대로 검색
        for lit in literals:
            try:
                rects += list(page.search_for(lit))
            except Exception:
                swallowed()
        # 정규식 프리셋: 페이지 텍스트에서 매치를 찾아 그 문자열을 다시 검색
        if patterns:
            try:
                text = page.get_text()
            except Exception:
                text = ''
            seen = set()
            for pat in patterns:
                try:
                    for m in re.finditer(pat, text):
                        s = m.group(0).strip()
                        if not s or s in seen:
                            continue
                        seen.add(s)
                        try:
                            rects += list(page.search_for(s))
                        except Exception:
                            swallowed()
                except re.error:
                    swallowed()
        return rects

    @staticmethod
    def apply(fitz_doc, page_indices: list[int], patterns: list[str],
              literals: list[str], show_label: bool) -> int:
        total = 0
        for i in page_indices:
            page = fitz_doc[i]
            rects = RedactDialog.collect_rects(page, patterns, literals)
            if not rects:
                continue
            for r in rects:
                kwargs = {'fill': (0, 0, 0)}
                if show_label:
                    kwargs['text'] = '삭제됨'
                    kwargs['text_color'] = (1, 1, 1)
                    kwargs['fontsize'] = max(6, min(10, r.height * 0.7))
                try:
                    page.add_redact_annot(r, **kwargs)
                    total += 1
                except Exception:
                    swallowed()
            try:
                page.apply_redactions()
            except Exception:
                swallowed()
        return total


# ════════════════════════════════════════════════════════════════════
# 3) 전자 서명 (가시 서명 — 이미지/텍스트)
# ════════════════════════════════════════════════════════════════════
class SignatureDialog(QDialog):
    """가시 서명(도장/이미지 또는 이름+날짜)을 현재 페이지에 배치."""

    _POSITIONS = [
        ('오른쪽 아래', 'br'), ('왼쪽 아래', 'bl'),
        ('오른쪽 위', 'tr'), ('왼쪽 위', 'tl'), ('가운데', 'c'),
    ]

    def __init__(self, parent=None, default_name: str = ''):
        super().__init__(parent)
        self.setWindowTitle('✍ 전자 서명 삽입')
        self.setMinimumWidth(440)
        ly = QVBoxLayout(self)

        note = QLabel('이름·도장 이미지를 페이지에 <b>가시 서명</b>으로 넣고 '
                      '문서 작성자 정보를 기록합니다.\n'
                      '(공인인증서 기반 암호화 서명은 이 버전에서 지원하지 않습니다.)')
        note.setWordWrap(True)
        note.setStyleSheet('color:#555;')
        ly.addWidget(note)

        # 모드
        mode_ly = QHBoxLayout()
        self._rb_text = QRadioButton('이름 + 날짜'); self._rb_text.setChecked(True)
        self._rb_image = QRadioButton('서명/도장 이미지')
        self._rb_text.toggled.connect(self._sync)
        mode_ly.addWidget(self._rb_text); mode_ly.addWidget(self._rb_image)
        mode_ly.addStretch(1)
        ly.addLayout(mode_ly)

        grid = QGridLayout()
        grid.addWidget(QLabel('서명자 이름'), 0, 0)
        self._name_ed = QLineEdit(default_name)
        grid.addWidget(self._name_ed, 0, 1, 1, 2)

        self._date_cb = QCheckBox('오늘 날짜 포함'); self._date_cb.setChecked(True)
        grid.addWidget(self._date_cb, 1, 1)

        grid.addWidget(QLabel('이미지 파일'), 2, 0)
        self._img_ed = QLineEdit()
        self._img_btn = QPushButton('찾아보기')
        self._img_btn.clicked.connect(self._pick_image)
        grid.addWidget(self._img_ed, 2, 1)
        grid.addWidget(self._img_btn, 2, 2)

        grid.addWidget(QLabel('위치'), 3, 0)
        self._pos_cb = QComboBox()
        for label, _ in self._POSITIONS:
            self._pos_cb.addItem(label)
        grid.addWidget(self._pos_cb, 3, 1)

        grid.addWidget(QLabel('크기'), 4, 0)
        self._size_sb = QSpinBox(); self._size_sb.setRange(20, 400); self._size_sb.setValue(120)
        self._size_sb.setSuffix(' pt')
        grid.addWidget(self._size_sb, 4, 1)

        grid.addWidget(QLabel('투명도'), 5, 0)
        opa = QHBoxLayout()
        self._opacity_sb = QSpinBox()
        self._opacity_sb.setRange(10, 100); self._opacity_sb.setValue(100)
        self._opacity_sb.setSuffix(' %')
        self._opacity_sb.setToolTip('낮출수록 도장이 비쳐서 본문 글자가 함께 보입니다.')
        opa.addWidget(self._opacity_sb)
        opa.addWidget(QLabel('(낮추면 본문이 비쳐 보입니다)'))
        opa.addStretch(1)
        grid.addLayout(opa, 5, 1)
        ly.addLayout(grid)

        rng = QHBoxLayout()
        rng.addWidget(QLabel('적용:'))
        self._range_cb = QComboBox()
        self._range_cb.addItems(['현재 페이지', '전체 페이지'])
        rng.addWidget(self._range_cb); rng.addStretch(1)
        ly.addLayout(rng)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('서명 삽입')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)
        self._sync()

    def _sync(self):
        is_text = self._rb_text.isChecked()
        self._name_ed.setEnabled(is_text)
        self._date_cb.setEnabled(is_text)
        self._img_ed.setEnabled(not is_text)
        self._img_btn.setEnabled(not is_text)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '서명/도장 이미지 선택', '',
            '이미지 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if path:
            self._img_ed.setText(path)

    def is_image(self) -> bool:
        return self._rb_image.isChecked()

    def name(self) -> str:
        return self._name_ed.text().strip()

    def with_date(self) -> bool:
        return self._date_cb.isChecked()

    def image_path(self) -> str:
        return self._img_ed.text().strip()

    def position(self) -> str:
        return self._POSITIONS[self._pos_cb.currentIndex()][1]

    def size_px(self) -> int:
        return self._size_sb.value()

    def opacity(self) -> float:
        """0.1 ~ 1.0"""
        return max(0.1, min(1.0, self._opacity_sb.value() / 100.0))

    def all_pages(self) -> bool:
        return self._range_cb.currentIndex() == 1

    @staticmethod
    def _dest_rect(page_rect: fitz.Rect, pos: str, w: float, h: float,
                   margin: float = 24.0) -> fitz.Rect:
        pw, ph = page_rect.width, page_rect.height
        if pos == 'br':
            x0, y0 = pw - margin - w, ph - margin - h
        elif pos == 'bl':
            x0, y0 = margin, ph - margin - h
        elif pos == 'tr':
            x0, y0 = pw - margin - w, margin
        elif pos == 'tl':
            x0, y0 = margin, margin
        else:  # center
            x0, y0 = (pw - w) / 2, (ph - h) / 2
        return fitz.Rect(x0, y0, x0 + w, y0 + h)

    @staticmethod
    def _fade_image(image_path: str, opacity: float) -> str:
        """이미지에 투명도를 입힌 임시 PNG 경로를 돌려준다 (실패 시 원본 경로).

        insert_image 는 투명도 인자가 없어서 알파 채널을 미리 곱해 둔다.
        """
        if opacity >= 0.99:
            return image_path
        try:
            import tempfile
            from PIL import Image as _Image
            img = _Image.open(image_path).convert('RGBA')
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * opacity))
            img = _Image.merge('RGBA', (r, g, b, a))
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            tmp.close()
            img.save(tmp.name)
            return tmp.name
        except Exception:
            return image_path

    @staticmethod
    def apply(fitz_doc, page_indices: list[int], *, is_image: bool,
              image_path: str, name: str, with_date: str,
              pos: str, size_px: int, opacity: float = 1.0) -> bool:
        import datetime
        ok = False
        faded = SignatureDialog._fade_image(image_path, opacity) if (is_image and image_path) else image_path
        for i in page_indices:
            page = fitz_doc[i]
            if is_image and image_path:
                try:
                    src = fitz.open(image_path)
                    sr = src[0].rect
                    ratio = size_px / max(sr.width, sr.height, 1)
                    w, h = sr.width * ratio, sr.height * ratio
                    src.close()
                    dest = SignatureDialog._dest_rect(page.rect, pos, w, h)
                    page.insert_image(dest, filename=faded, overlay=True,
                                      keep_proportion=True)
                    ok = True
                except Exception:
                    swallowed()
            else:
                lines = [name] if name else []
                if with_date:
                    lines.append(datetime.date.today().strftime('%Y-%m-%d'))
                if not lines:
                    continue
                label = '  '.join(lines)
                fontsize = max(10, size_px * 0.14)
                w = max(90, len(label) * fontsize * 0.62 + 20)
                h = fontsize * 2.4
                dest = SignatureDialog._dest_rect(page.rect, pos, w, h)
                # 서명 테두리 상자
                op = max(0.1, min(1.0, opacity))
                try:
                    # 한글이 섞이면 내장 CJK 폰트로 그려야 글자가 깨지지 않는다.
                    korean = any(0xAC00 <= ord(c) <= 0xD7A3 for c in label)
                    fontname = 'korea' if korean else 'helv'
                    inner = dest + (6, 4, -6, -4)
                    page.draw_rect(dest, color=(0.15, 0.25, 0.6), width=1.2,
                                   stroke_opacity=op)
                    page.insert_textbox(inner, label, fontname=fontname,
                                        fontsize=fontsize, color=(0.15, 0.25, 0.6),
                                        align=fitz.TEXT_ALIGN_CENTER,
                                        stroke_opacity=op, fill_opacity=op)
                    ok = True
                except Exception:
                    swallowed()
        if faded != image_path:
            try:
                import os as _os
                _os.unlink(faded)
            except OSError:
                swallowed()
        # 작성자 메타데이터 기록
        if ok and name:
            try:
                md = fitz_doc.metadata or {}
                md['author'] = name
                fitz_doc.set_metadata(md)
            except Exception:
                swallowed()
        return ok
