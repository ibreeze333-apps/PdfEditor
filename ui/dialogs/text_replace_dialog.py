# ui/dialogs/text_replace_dialog.py — PDF 텍스트 찾아 교체 (개선판)
# 원리: search_for → redact (흰색 덮기) → insert_text (새 텍스트 삽입)
# 개선: 원본 폰트 크기 자동 감지, 교체 후 다이얼로그 유지, 대소문자 옵션, 폰트 선택
from __future__ import annotations
import os
import fitz

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QCheckBox, QPushButton,
    QSpinBox, QGroupBox, QComboBox,
)
from utils.errlog import swallowed


def _has_cjk(text: str) -> bool:
    for c in text:
        cp = ord(c)
        if (0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF or
                0x3000 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF):
            return True
    return False


# (표시명, 폰트파일경로, PDF내부명)  — 파일 없는 항목은 콤보에서 제외
_FONT_TABLE = [
    ('원본 폰트 유지 (자동)',             None,                                           None),
    ('KoPub 바탕 Light',                  'C:/Windows/Fonts/KoPub Batang Light.ttf',      'KPBL'),
    ('KoPub 바탕 Medium',                 'C:/Windows/Fonts/KoPub Batang Medium.ttf',     'KPBT'),
    ('KoPub 바탕 Bold',                   'C:/Windows/Fonts/KoPub Batang Bold.ttf',       'KPBB'),
    ('KoPub 돋움 Light',                  'C:/Windows/Fonts/KoPub Dotum Light.ttf',       'KPDL'),
    ('KoPub 돋움 Medium',                 'C:/Windows/Fonts/KoPub Dotum Medium.ttf',      'KPDT'),
    ('KoPub 돋움 Bold',                   'C:/Windows/Fonts/KoPub Dotum Bold.ttf',        'KPDB'),
    ('맑은 고딕',                         'C:/Windows/Fonts/malgun.ttf',                  'MLGG'),
    ('맑은 고딕 Bold',                    'C:/Windows/Fonts/malgunbd.ttf',                'MLGB'),
    ('함초롬바탕',                        'C:/Windows/Fonts/HANBatang.ttf',               'HNBT'),
    ('함초롬바탕 Bold',                   'C:/Windows/Fonts/HANBatangB.ttf',              'HNBB'),
    ('굴림',                              'C:/Windows/Fonts/gulim.ttc',                   'GULM'),
    ('바탕',                              'C:/Windows/Fonts/batang.ttc',                  'BATG'),
    ('돋움',                              'C:/Windows/Fonts/dotum.ttc',                   'DOTM'),
    ('Times New Roman',                   'C:/Windows/Fonts/times.ttf',                   'TIMR'),
    ('Arial',                             'C:/Windows/Fonts/arial.ttf',                   'ARAL'),
]

# 실제 파일이 있는 항목만 남긴다 (첫 항목 '자동'은 항상 포함)
_AVAILABLE_FONTS = [_FONT_TABLE[0]] + [
    row for row in _FONT_TABLE[1:]
    if row[1] and os.path.exists(row[1])
]


class TextReplaceDialog(QDialog):
    """PDF 텍스트 찾아 교체 다이얼로그."""

    def __init__(self, fitz_doc: fitz.Document, current_page: int, parent=None):
        super().__init__(parent)
        self._doc          = fitz_doc
        self._current_page = current_page
        self._replaced     = 0
        self._setui()
        self.setWindowTitle('PDF 텍스트 찾아 교체')
        self.resize(520, 390)

    def _setui(self):
        lay = QVBoxLayout(self)

        # ── 범위 ──────────────────────────────────────────────────────
        scope_grp = QGroupBox('교체 범위')
        scope_lay = QHBoxLayout(scope_grp)
        self._rb_current = QCheckBox('현재 페이지만')
        self._rb_current.setChecked(True)
        self._rb_all = QCheckBox('전체 페이지')
        self._rb_current.toggled.connect(lambda c: self._rb_all.setChecked(not c))
        self._rb_all.toggled.connect(lambda c: self._rb_current.setChecked(not c))
        scope_lay.addWidget(self._rb_current)
        scope_lay.addWidget(self._rb_all)
        lay.addWidget(scope_grp)

        # ── 찾기 ──────────────────────────────────────────────────────
        lay.addWidget(QLabel('찾을 텍스트:'))
        self._find_ed = QLineEdit()
        self._find_ed.setPlaceholderText('찾을 문자열 입력...')
        self._find_ed.returnPressed.connect(self._apply)
        lay.addWidget(self._find_ed)

        # ── 교체 ──────────────────────────────────────────────────────
        lay.addWidget(QLabel('바꿀 텍스트 (빈 칸 = 삭제):'))
        self._repl_ed = QLineEdit()
        self._repl_ed.setPlaceholderText('바꿀 문자열 (비워두면 해당 텍스트만 삭제)')
        self._repl_ed.returnPressed.connect(self._apply)
        lay.addWidget(self._repl_ed)

        # ── 폰트 선택 ─────────────────────────────────────────────────
        font_lay = QHBoxLayout()
        font_lay.addWidget(QLabel('바꿀 텍스트 폰트:'))
        self._font_cb = QComboBox()
        for label, *_ in _AVAILABLE_FONTS:
            self._font_cb.addItem(label)
        font_lay.addWidget(self._font_cb, 1)
        lay.addLayout(font_lay)

        # ── 옵션 ──────────────────────────────────────────────────────
        opt_lay = QHBoxLayout()
        self._cb_case = QCheckBox('대소문자 구분')
        self._cb_case.setChecked(False)
        opt_lay.addWidget(self._cb_case)
        opt_lay.addSpacing(20)
        self._cb_auto_fs = QCheckBox('글자 크기 자동 감지')
        self._cb_auto_fs.setChecked(True)
        self._cb_auto_fs.stateChanged.connect(
            lambda s: self._font_sz.setEnabled(not bool(s)))
        opt_lay.addWidget(self._cb_auto_fs)
        opt_lay.addSpacing(8)
        opt_lay.addWidget(QLabel('수동 크기:'))
        self._font_sz = QSpinBox()
        self._font_sz.setRange(4, 72)
        self._font_sz.setValue(11)
        self._font_sz.setEnabled(False)
        opt_lay.addWidget(self._font_sz)
        opt_lay.addStretch()
        lay.addLayout(opt_lay)

        # ── 결과 ──────────────────────────────────────────────────────
        self._result_lbl = QLabel('⚠ 원본 PDF 텍스트를 영구 수정합니다. 저장 전에 확인하세요.')
        self._result_lbl.setStyleSheet('color: #cc6600;')
        self._result_lbl.setWordWrap(True)
        lay.addWidget(self._result_lbl)

        # ── 버튼 ──────────────────────────────────────────────────────
        btn_lay = QHBoxLayout()
        self._preview_btn = QPushButton('🔍 미리보기')
        self._preview_btn.clicked.connect(self._preview)
        self._apply_btn = QPushButton('✅ 교체 실행')
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._apply)
        close_btn = QPushButton('닫기')
        close_btn.clicked.connect(self._close_with_result)
        btn_lay.addWidget(self._preview_btn)
        btn_lay.addWidget(self._apply_btn)
        btn_lay.addStretch()
        btn_lay.addWidget(close_btn)
        lay.addLayout(btn_lay)

    def _close_with_result(self):
        if self._replaced > 0:
            self.accept()
        else:
            self.reject()

    # ── 선택된 폰트 정보 반환 ────────────────────────────────────────
    def _selected_font(self) -> tuple[str, str] | None:
        """(fontfile_path, pdf_internal_name) 또는 자동(None) 반환."""
        idx = self._font_cb.currentIndex()
        _, fpath, fname = _AVAILABLE_FONTS[idx]
        if fpath is None:
            return None   # '자동' 선택
        return fpath, fname

    # ── 범위 헬퍼 ────────────────────────────────────────────────────
    def _page_range(self) -> range:
        if self._rb_all.isChecked():
            return range(self._doc.page_count)
        return range(self._current_page, self._current_page + 1)

    # ── 원본 폰트 크기 감지 ──────────────────────────────────────────
    def _detect_fontsize(self, page: fitz.Page, rect: fitz.Rect) -> float | None:
        try:
            blocks = page.get_text('dict', clip=rect)['blocks']
            for b in blocks:
                for line in b.get('lines', []):
                    for span in line.get('spans', []):
                        fs = span.get('size', 0)
                        if fs > 2:
                            return float(fs)
        except Exception:
            swallowed()
        return None

    # ── 미리보기 ─────────────────────────────────────────────────────
    def _preview(self):
        find = self._find_ed.text()
        if not find:
            self._result_lbl.setText('찾을 텍스트를 입력하세요.')
            return
        total = 0
        for idx in self._page_range():
            page = self._doc.load_page(idx)
            hits = page.search_for(find, quads=False)
            total += len(hits)
        scope = '전체 페이지' if self._rb_all.isChecked() \
                else f'페이지 {self._current_page + 1}'
        self._result_lbl.setStyleSheet('color: #1a5ca8;')
        self._result_lbl.setText(f'"{find}" → {scope}에서 {total}군데 발견됨.')

    # ── 교체 실행 ────────────────────────────────────────────────────
    def _apply(self):
        find = self._find_ed.text()
        repl = self._repl_ed.text()
        if not find:
            self._result_lbl.setText('찾을 텍스트를 입력하세요.')
            return

        total_replaced = 0
        manual_fs  = self._font_sz.value()
        auto_fs    = self._cb_auto_fs.isChecked()
        sel_font   = self._selected_font()   # None = 자동

        # '자동'일 때: 한글이면 첫 번째 가용 한글 폰트, 영문이면 helv
        if sel_font is None and repl and _has_cjk(repl):
            # _AVAILABLE_FONTS[0]은 '자동' 항목이므로 1번부터 탐색
            for _, fpath, fname in _AVAILABLE_FONTS[1:]:
                if fpath and os.path.exists(fpath):
                    sel_font = (fpath, fname)
                    break

        for idx in self._page_range():
            page = self._doc.load_page(idx)
            hits = page.search_for(find)
            if not hits:
                continue

            # 폰트 크기 감지 (첫 hit 기준)
            detected_fs = None
            if auto_fs and hits:
                detected_fs = self._detect_fontsize(page, hits[0])
            fs = detected_fs if (auto_fs and detected_fs) else manual_fs

            # 좌표를 먼저 복사 (apply_redactions 전에)
            rects = [fitz.Rect(r) for r in hits]

            # Redaction으로 원본 텍스트 지우기
            for rect in rects:
                page.add_redact_annot(rect, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            # 같은 위치에 새 텍스트 삽입
            if repl:
                for rect in rects:
                    baseline_y = rect.y1 - max(1.0, (rect.height - fs) * 0.5)
                    pt = fitz.Point(rect.x0, baseline_y)
                    try:
                        if sel_font:
                            fpath, fname = sel_font
                            page.insert_text(pt, repl, fontsize=fs,
                                             color=(0, 0, 0),
                                             fontfile=fpath, fontname=fname)
                        else:
                            page.insert_text(pt, repl, fontsize=fs,
                                             color=(0, 0, 0), fontname='helv')
                    except Exception as e:
                        print(f'[TextReplace] insert_text 오류: {e}')

            total_replaced += len(rects)

        self._replaced += total_replaced
        if total_replaced:
            scope = '전체' if self._rb_all.isChecked() \
                    else f'페이지 {self._current_page + 1}'
            self._result_lbl.setStyleSheet('color: #1a7f1a; font-weight: bold;')
            self._result_lbl.setText(
                f'✅ {scope}에서 {total_replaced}군데 교체 완료.  저장해야 반영됩니다.')
        else:
            self._result_lbl.setStyleSheet('color: #cc3300;')
            self._result_lbl.setText(f'"{find}"을 찾지 못했습니다.')

    def replaced_count(self) -> int:
        return self._replaced
