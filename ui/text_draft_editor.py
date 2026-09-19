from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSizeF, QMarginsF, Signal, QUrl, QTimer
from PySide6.QtGui import (
    QFont, QFontDatabase, QTextCursor, QTextDocument, QTextCharFormat, QTextBlockFormat,
    QTextListFormat, QTextTableFormat, QTextLength, QTextImageFormat,
    QTextFormat, QPageLayout, QPageSize, QPdfWriter, QColor,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSpinBox, QFrame, QComboBox, QColorDialog, QFileDialog, QMessageBox,
    QDialog, QGridLayout, QFontComboBox, QFontDialog, QDialogButtonBox, QLineEdit,
    QCheckBox,
)
from utils.errlog import swallowed

_PROPORTIONAL = 1   # QTextBlockFormat.LineHeightTypes.ProportionalHeight.value


# ─────────────────────────────────────────────────────────────────────────────
#  찾기 / 바꾸기 바
# ─────────────────────────────────────────────────────────────────────────────
class _FindReplaceBar(QWidget):
    def __init__(self, editor: 'TextDraftEditor'):
        super().__init__(editor)
        self._editor = editor
        self._build()
        self.hide()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        lay.addWidget(QLabel('찾기:'))
        self._find = QLineEdit()
        self._find.setPlaceholderText('찾을 내용')
        self._find.setFixedWidth(160)
        self._find.returnPressed.connect(self._next)
        lay.addWidget(self._find)

        lay.addWidget(QLabel('바꾸기:'))
        self._repl = QLineEdit()
        self._repl.setPlaceholderText('바꿀 내용')
        self._repl.setFixedWidth(160)
        lay.addWidget(self._repl)

        self._case = QCheckBox('대/소문자')
        self._word = QCheckBox('단어 단위')
        lay.addWidget(self._case)
        lay.addWidget(self._word)

        for label, slot in [('이전', self._prev), ('다음', self._next),
                             ('바꾸기', self._replace_one),
                             ('모두 바꾸기', self._replace_all)]:
            b = QPushButton(label)
            b.setFixedHeight(24)
            b.setStyleSheet(
                'QPushButton{padding:0 8px;border:1px solid #bbb;'
                'border-radius:3px;background:#fff;}'
                'QPushButton:hover{background:#e0e0e0;}')
            b.clicked.connect(slot)
            lay.addWidget(b)

        self._info = QLabel('')
        self._info.setStyleSheet('color:#888;font-size:11px;')
        lay.addWidget(self._info)
        lay.addStretch()
        close_b = QPushButton('X')
        close_b.setFixedSize(24, 24)
        close_b.setStyleSheet(
            'QPushButton{border:none;background:transparent;color:#888;}'
            'QPushButton:hover{color:#333;}')
        close_b.clicked.connect(self.hide)
        lay.addWidget(close_b)

        self.setStyleSheet(
            'QWidget{background:#f5f5f5;border-top:1px solid #ccc;}'
            'QLineEdit{background:white;border:1px solid #bbb;'
            'border-radius:3px;padding:2px 5px;}')

    def show_and_focus(self):
        self.show()
        self._find.setFocus()
        self._find.selectAll()

    def _flags(self, backward=False):
        f = QTextDocument.FindFlag(0)
        if backward:
            f |= QTextDocument.FindFlag.FindBackward
        if self._case.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        if self._word.isChecked():
            f |= QTextDocument.FindFlag.FindWholeWords
        return f

    def _find_text(self, backward=False) -> bool:
        text = self._find.text()
        if not text:
            return False
        ed = self._editor.editor()
        found = ed.find(text, self._flags(backward))
        if not found:
            cur = ed.textCursor()
            cur.movePosition(
                QTextCursor.MoveOperation.End if backward
                else QTextCursor.MoveOperation.Start)
            ed.setTextCursor(cur)
            found = ed.find(text, self._flags(backward))
        self._info.setText('' if found else '찾을 수 없습니다.')
        return found

    def _next(self): self._find_text(False)
    def _prev(self): self._find_text(True)

    def _replace_one(self):
        ed = self._editor.editor()
        if ed.textCursor().hasSelection():
            ed.textCursor().insertText(self._repl.text())
        self._find_text(False)

    def _replace_all(self):
        search = self._find.text()
        if not search:
            return
        ed = self._editor.editor()
        doc = ed.document()
        cursor = QTextCursor(doc)
        count = 0
        cursor.beginEditBlock()
        while True:
            cursor = doc.find(search, cursor, self._flags())
            if cursor.isNull():
                break
            cursor.insertText(self._repl.text())
            count += 1
        cursor.endEditBlock()
        self._info.setText(f'{count}개 바꿨습니다.' if count else '찾을 수 없습니다.')


# ─────────────────────────────────────────────────────────────────────────────
#  표 삽입 대화상자
# ─────────────────────────────────────────────────────────────────────────────
class _TableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('표 삽입')
        self.setFixedSize(220, 130)
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel('행 수:'), 0, 0)
        self._r = QSpinBox(); self._r.setRange(1, 50); self._r.setValue(3)
        grid.addWidget(self._r, 0, 1)
        grid.addWidget(QLabel('열 수:'), 1, 0)
        self._c = QSpinBox(); self._c.setRange(1, 20); self._c.setValue(3)
        grid.addWidget(self._c, 1, 1)
        lay.addLayout(grid)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return self._r.value(), self._c.value()


# ─────────────────────────────────────────────────────────────────────────────
#  페이지 설정 대화상자
# ─────────────────────────────────────────────────────────────────────────────
class _PageSetupDialog(QDialog):
    _SIZES = [
        ('A4',     QPageSize.PageSizeId.A4),
        ('A3',     QPageSize.PageSizeId.A3),
        ('A5',     QPageSize.PageSizeId.A5),
        ('Letter', QPageSize.PageSizeId.Letter),
        ('Legal',  QPageSize.PageSizeId.Legal),
        ('B5',     QPageSize.PageSizeId.B5),
    ]

    def __init__(self, size_id, orientation, margin_mm, parent=None):
        super().__init__(parent)
        self.setWindowTitle('페이지 설정')
        self.setFixedSize(280, 175)
        lay = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel('용지 크기:'), 0, 0)
        self._sz = QComboBox()
        for name, _ in self._SIZES:
            self._sz.addItem(name)
        ids = [s[1] for s in self._SIZES]
        self._sz.setCurrentIndex(ids.index(size_id) if size_id in ids else 0)
        grid.addWidget(self._sz, 0, 1)

        grid.addWidget(QLabel('방향:'), 1, 0)
        self._or = QComboBox()
        self._or.addItems(['세로 (Portrait)', '가로 (Landscape)'])
        self._or.setCurrentIndex(
            0 if orientation == QPageLayout.Orientation.Portrait else 1)
        grid.addWidget(self._or, 1, 1)

        grid.addWidget(QLabel('여백 (mm):'), 2, 0)
        self._mg = QSpinBox(); self._mg.setRange(0, 80); self._mg.setValue(int(margin_mm))
        grid.addWidget(self._mg, 2, 1)

        lay.addLayout(grid)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        size_id = self._SIZES[self._sz.currentIndex()][1]
        orient = (QPageLayout.Orientation.Portrait
                  if self._or.currentIndex() == 0
                  else QPageLayout.Orientation.Landscape)
        return size_id, orient, float(self._mg.value())


# ─────────────────────────────────────────────────────────────────────────────
#  메인 문서 작성기
# ─────────────────────────────────────────────────────────────────────────────
class TextDraftEditor(QWidget):
    modified_changed = Signal(bool)
    cursor_changed   = Signal(int, int)
    close_requested = Signal()
    _STYLES: dict[str, tuple] = {
        '본문':   (0,  False, 0, 'normal'),
        '제목 1': (28, True,  1, 'heading'),
        '제목 2': (22, True,  2, 'heading'),
        '제목 3': (18, True,  3, 'heading'),
        '제목 4': (14, True,  4, 'heading'),
        '소제목': (13, True,  0, 'subtitle'),
        '코드':   (11, False, 0, 'code'),
        '인용문': (12, False, 0, 'quote'),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_font       = QFont('Malgun Gothic', 12)
        self._text_color      = QColor('#000000')
        self._hl_color        = QColor('#FFFF00')
        self._page_size_id    = QPageSize.PageSizeId.A4
        self._orientation     = QPageLayout.Orientation.Portrait
        self._margin_mm       = 20.0
        self._inhibit_sync    = False   # 툴바 ↔ 커서 동기화 중 재진입 방지
        self._build_ui()
        self.new_document()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_row1())
        root.addWidget(self._build_row2())

        self._edit = QTextEdit(self)
        self._edit.setAcceptRichText(True)
        # padding 은 CSS 대신 documentMargin 으로 — CSS padding 은 QTextEdit 에서 crash 유발 가능
        self._edit.setStyleSheet('QTextEdit { background: white; border: none; }')
        self._edit.document().setDocumentMargin(40.0)
        root.addWidget(self._edit, 1)

        self._find_bar = _FindReplaceBar(self)
        root.addWidget(self._find_bar)
        root.addWidget(self._build_status_bar())

        # 신호 연결 (편집기 생성 후)
        self._edit.document().modificationChanged.connect(self.modified_changed.emit)
        self._edit.cursorPositionChanged.connect(self._on_cursor_changed)
        # currentCharFormatChanged 는 Qt 폰트 시스템 처리 도중 emit 되면
        # fontFamily() 등 내부 COM/DirectWrite 호출이 access violation 유발.
        # → 다음 이벤트 루프로 완전히 지연하여 Qt 내부 상태가 안정된 뒤 처리.
        self._edit.currentCharFormatChanged.connect(
            lambda _: QTimer.singleShot(0, self._sync_toolbar_from_cursor))
        self._edit.document().contentsChanged.connect(self._schedule_stats)

        self._btn_undo.clicked.connect(self._edit.undo)
        self._btn_redo.clicked.connect(self._edit.redo)
        self._edit.document().undoAvailable.connect(self._btn_undo.setEnabled)
        self._edit.document().redoAvailable.connect(self._btn_redo.setEnabled)
        self._btn_undo.setEnabled(False)
        self._btn_redo.setEnabled(False)

    # ─── Row 1: 글자 서식 ────────────────────────────────────────────────────

    def _build_row1(self) -> QFrame:
        f = self._bar_frame()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(3)

        # ── 실행취소 / 재실행 ──────────────────────────────────────────
        self._btn_undo = self._mk_btn('↩ 취소',   '실행 취소 (Ctrl+Z)')
        self._btn_redo = self._mk_btn('↪ 재실행', '다시 실행 (Ctrl+Y)')
        lay.addWidget(self._btn_undo)
        lay.addWidget(self._btn_redo)
        lay.addWidget(self._sep())

        # ── 글자 서식 버튼 ─────────────────────────────────────────────
        self._btn_bold = self._mk_btn('B', '굵게 (Ctrl+B)', checkable=True, w=34)
        self._btn_bold.setFont(QFont('Malgun Gothic', 12, QFont.Weight.Bold))
        lay.addWidget(self._btn_bold)

        self._btn_italic = self._mk_btn('I', '기울임 (Ctrl+I)', checkable=True, w=34)
        _fi = QFont('Malgun Gothic', 12); _fi.setItalic(True)
        self._btn_italic.setFont(_fi)
        lay.addWidget(self._btn_italic)

        self._btn_under = self._mk_btn('U', '밑줄 (Ctrl+U)', checkable=True, w=34)
        _fu = QFont('Malgun Gothic', 12); _fu.setUnderline(True)
        self._btn_under.setFont(_fu)
        lay.addWidget(self._btn_under)

        self._btn_strike = self._mk_btn('S', '취소선', checkable=True, w=34)
        _fs = QFont('Malgun Gothic', 12); _fs.setStrikeOut(True)
        self._btn_strike.setFont(_fs)
        lay.addWidget(self._btn_strike)

        self._btn_super = self._mk_btn('x\u00b2', '위첨자', checkable=True, w=34)
        lay.addWidget(self._btn_super)

        self._btn_sub = self._mk_btn('x\u2082', '아래첨자', checkable=True, w=34)
        lay.addWidget(self._btn_sub)

        lay.addWidget(self._sep())

        # ── 글꼴 + 크기 ────────────────────────────────────────────────
        self._font_combo = QFontComboBox()
        self._font_combo.setWritingSystem(QFontDatabase.WritingSystem.Korean)
        self._font_combo.setFixedWidth(185)
        self._font_combo.setFixedHeight(30)
        self._font_combo.setStyleSheet(self._COMBO_SS)
        lay.addWidget(self._font_combo)

        self._btn_font_picker = self._mk_btn('...', '\uae00\uaf34 \uc120\ud0dd', w=40)
        lay.addWidget(self._btn_font_picker)

        lay.addSpacing(3)

        self._size_sb = QSpinBox()
        self._size_sb.setRange(4, 144)
        self._size_sb.setFixedWidth(54)
        self._size_sb.setFixedHeight(30)
        self._size_sb.setStyleSheet(self._SPIN_SS)
        lay.addWidget(self._size_sb)

        _pt = QLabel('pt')
        _pt.setStyleSheet('color:#555; font-size:11px;')
        lay.addWidget(_pt)

        lay.addWidget(self._sep())

        # ── 색상 버튼 ──────────────────────────────────────────────────
        self._btn_color  = self._mk_btn('A',  '글자 색상', w=36)
        self._btn_hl     = self._mk_btn('형광', '형광펜 색상')
        self._btn_hl_clr = self._mk_btn('형광 지우기', '형광펜 지우기')
        lay.addWidget(self._btn_color)
        lay.addWidget(self._btn_hl)
        lay.addWidget(self._btn_hl_clr)

        lay.addWidget(self._sep())

        # ── 찾기/바꾸기 ────────────────────────────────────────────────
        btn_find = self._mk_btn('찾기 / 바꾸기', '찾기 · 바꾸기 (Ctrl+F)')
        btn_find.setShortcut('Ctrl+F')
        btn_find.clicked.connect(self.show_find)
        lay.addWidget(btn_find)

        lay.addStretch()

        self._btn_close_draft = self._mk_btn('\ub05d\ub0b4\uae30', '\uc0c8 \ubb38\uc11c \uc791\uc131 \ubaa8\ub4dc \uc885\ub8cc')
        self._btn_close_draft.clicked.connect(self.close_requested.emit)
        lay.addWidget(self._btn_close_draft)

        # ── 신호 연결 (setValue/setCurrentFont 이후에) ─────────────────
        self._btn_bold.toggled.connect(self._apply_bold)
        self._btn_italic.toggled.connect(self._apply_italic)
        self._btn_under.toggled.connect(self._apply_underline)
        self._btn_strike.toggled.connect(self._apply_strikeout)
        self._btn_super.toggled.connect(lambda c: self._apply_valign(c, True))
        self._btn_sub.toggled.connect(lambda c: self._apply_valign(c, False))
        self._font_combo.currentFontChanged.connect(self._apply_font_family)
        self._btn_font_picker.clicked.connect(self._choose_font_dialog)
        self._size_sb.valueChanged.connect(self._apply_font_size)
        self._btn_color.clicked.connect(self._pick_text_color)
        self._btn_hl.clicked.connect(self._pick_highlight)
        self._btn_hl_clr.clicked.connect(self._clear_highlight)

        return f

    # ─── Row 2: 단락 서식 + 삽입 ────────────────────────────────────────────

    def _build_row2(self) -> QFrame:
        f = self._bar_frame()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(3)

        # ── 정렬 ───────────────────────────────────────────────────────
        self._btn_al = self._mk_btn('좌', '왼쪽 정렬',   checkable=True, w=36)
        self._btn_ac = self._mk_btn('중', '가운데 정렬', checkable=True, w=36)
        self._btn_ar = self._mk_btn('우', '오른쪽 정렬', checkable=True, w=36)
        self._btn_aj = self._mk_btn('양', '양쪽 정렬',   checkable=True, w=36)
        self._align_btns = [self._btn_al, self._btn_ac, self._btn_ar, self._btn_aj]
        self._align_vals = [
            Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter,
            Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignJustify,
        ]
        for btn, val in zip(self._align_btns, self._align_vals):
            btn.clicked.connect(lambda _, v=val: self._set_alignment(v))
            lay.addWidget(btn)
        self._btn_al.setChecked(True)

        lay.addWidget(self._sep())

        # ── 목록 / 들여쓰기 ────────────────────────────────────────────
        self._btn_bul = self._mk_btn('\u2022 목록', '글머리 기호 목록', checkable=True)
        self._btn_bul.clicked.connect(self._toggle_bullet)
        lay.addWidget(self._btn_bul)

        self._btn_num = self._mk_btn('1. 목록', '번호 목록', checkable=True)
        self._btn_num.clicked.connect(self._toggle_numbered)
        lay.addWidget(self._btn_num)

        btn_in = self._mk_btn('\u2192 들여쓰기', '들여쓰기')
        btn_in.clicked.connect(self._indent_more)
        lay.addWidget(btn_in)

        btn_out = self._mk_btn('\u2190 내어쓰기', '내어쓰기')
        btn_out.clicked.connect(self._indent_less)
        lay.addWidget(btn_out)

        lay.addWidget(self._sep())

        # ── 단락 스타일 — 신호 연결 전에 items 추가 ───────────────────
        _lbl_style = QLabel('스타일')
        _lbl_style.setStyleSheet('color:#555; font-size:11px;')
        lay.addWidget(_lbl_style)
        self._style_cb = QComboBox()
        self._style_cb.setFixedWidth(92)
        self._style_cb.setFixedHeight(30)
        self._style_cb.setStyleSheet(self._COMBO_SS)
        for name in self._STYLES:
            self._style_cb.addItem(name)
        lay.addWidget(self._style_cb)

        lay.addSpacing(4)

        # ── 줄 간격 — 신호 연결 전에 items 추가 ───────────────────────
        _lbl_sp = QLabel('줄간격')
        _lbl_sp.setStyleSheet('color:#555; font-size:11px;')
        lay.addWidget(_lbl_sp)
        self._spacing_cb = QComboBox()
        self._spacing_cb.setFixedWidth(62)
        self._spacing_cb.setFixedHeight(30)
        self._spacing_cb.setStyleSheet(self._COMBO_SS)
        self._spacing_cb.addItems(['1.0', '1.15', '1.5', '2.0', '2.5'])
        self._spacing_cb.setCurrentIndex(1)
        lay.addWidget(self._spacing_cb)

        lay.addWidget(self._sep())

        # ── 삽입 버튼 ──────────────────────────────────────────────────
        for label, tip, slot in [
            ('표 삽입',   '표 삽입',           self._insert_table),
            ('이미지',    '이미지 파일 삽입',   self._insert_image),
            ('구분선',    '가로 구분선 삽입',   self._insert_hr),
            ('페이지\u2193', '페이지 나누기', self._insert_page_break),
            ('날짜',      '오늘 날짜 삽입',     self._insert_date),
        ]:
            b = self._mk_btn(label, tip)
            b.clicked.connect(slot)
            lay.addWidget(b)

        lay.addWidget(self._sep())

        btn_pg = self._mk_btn('페이지 설정', '용지 크기 · 방향 · 여백 설정')
        btn_pg.clicked.connect(self._show_page_setup)
        lay.addWidget(btn_pg)

        lay.addStretch()

        # ── 신호 연결 (addItems / setCurrentIndex 이후에) ──────────────
        self._style_cb.currentTextChanged.connect(self._apply_style)
        self._spacing_cb.currentIndexChanged.connect(self._apply_line_spacing)

        return f

    # ─── 상태 바 ────────────────────────────────────────────────────────────

    def _build_status_bar(self) -> QFrame:
        f = QFrame()
        f.setFixedHeight(26)
        f.setStyleSheet('QFrame{background:#f0f0f0;border-top:1px solid #ddd;}')
        lay = QHBoxLayout(f)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(14)

        self._lbl_chars  = QLabel('글자: 0')
        self._lbl_words  = QLabel('단어: 0')
        self._lbl_lines  = QLabel('줄: 0')
        self._lbl_cursor = QLabel('1행 1열')
        for lbl in (self._lbl_chars, self._lbl_words, self._lbl_lines, self._lbl_cursor):
            lbl.setStyleSheet('color:#555;font-size:11px;')
            lay.addWidget(lbl)

        lay.addStretch()

        for text, tip, cb in [
            ('HTML 저장', 'HTML로 내보내기', self._export_html),
            ('TXT 저장',  'TXT로 내보내기',  self._export_txt),
        ]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedHeight(20)
            b.setStyleSheet(
                'QPushButton{padding:0 8px;font-size:11px;border:1px solid #bbb;'
                'border-radius:3px;background:#fff;}'
                'QPushButton:hover{background:#e0eaff;}')
            b.clicked.connect(cb)
            lay.addWidget(b)

        return f

    # ─── 헬퍼 ───────────────────────────────────────────────────────────────

    # 공통 스타일 상수
    _ACCENT   = '#4361ee'
    _ACCENT_D = '#2f4ccc'
    _ACCENT_T = '#eef1fd'

    _COMBO_SS = (
        'QComboBox {'
        '  border: 1.5px solid #c8ccd6; border-radius: 5px;'
        '  background: #ffffff; padding: 1px 8px;'
        '  font-size: 12px; color: #2c3148; }'
        'QComboBox:hover { border-color: #4361ee; }'
        'QComboBox::drop-down { border: none; width: 20px; }'
        'QComboBox QAbstractItemView { border: 1px solid #c8ccd6; }'
    )
    _SPIN_SS = (
        'QSpinBox {'
        '  border: 1.5px solid #c8ccd6; border-radius: 5px;'
        '  background: #ffffff; padding: 1px 4px;'
        '  font-size: 12px; color: #2c3148; }'
        'QSpinBox:hover { border-color: #4361ee; }'
    )

    @staticmethod
    def _bar_frame() -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            'QFrame { background: #f3f4f8; border-bottom: 1.5px solid #d0d4e0; }')
        return f

    @staticmethod
    def _sep() -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.Shape.VLine)
        s.setFixedWidth(1)
        s.setFixedHeight(22)
        s.setStyleSheet('background: #c8ccd6; margin: 0 5px;')
        return s

    @staticmethod
    def _mk_btn(text: str, tip: str = '', checkable: bool = False,
                w: int = 0) -> QPushButton:
        b = QPushButton(text)
        if tip:
            b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFixedHeight(30)
        if w:
            b.setFixedWidth(w)
        b.setStyleSheet(
            'QPushButton {'
            '  padding: 0 10px;'
            '  border: 1.5px solid #c8ccd6;'
            '  border-radius: 5px;'
            '  background: #ffffff;'
            '  color: #2c3148;'
            '  font-size: 12px;'
            '}'
            'QPushButton:hover {'
            '  background: #eef1fd;'
            '  border-color: #4361ee;'
            '  color: #4361ee;'
            '}'
            'QPushButton:checked {'
            '  background: #4361ee;'
            '  border-color: #2f4ccc;'
            '  color: #ffffff;'
            '  font-weight: 600;'
            '}'
            'QPushButton:pressed {'
            '  background: #2f4ccc;'
            '  color: #ffffff;'
            '}'
            'QPushButton:disabled {'
            '  background: #f5f5f7;'
            '  border-color: #e2e4ea;'
            '  color: #b8bcc8;'
            '}'
        )
        return b

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def editor(self) -> QTextEdit:
        return self._edit

    def new_document(self):
        """편집기 초기화 — 신호 루프 없이 안전하게."""
        self._inhibit_sync = True
        try:
            self._edit.blockSignals(True)
            self._edit.clear()
            self._edit.blockSignals(False)

            self._edit.document().setModified(False)

            # 기본 글꼴 적용
            self._edit.setFont(self._base_font)

            # 기본 줄 간격 설정 (1.15배)
            cur = self._edit.textCursor()
            bf = QTextBlockFormat()
            bf.setLineHeight(115.0, _PROPORTIONAL)
            cur.setBlockFormat(bf)
            self._edit.setTextCursor(cur)
        finally:
            self._inhibit_sync = False

        # 툴바 초기 상태 동기화
        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentFont(self._base_font)
        self._font_combo.blockSignals(False)
        self._size_sb.blockSignals(True)
        self._size_sb.setValue(self._base_font.pointSize())
        self._size_sb.blockSignals(False)

        self._update_stats()

    def is_modified(self) -> bool:
        return self._edit.document().isModified()

    def plain_text(self) -> str:
        return self._edit.toPlainText()

    def show_find(self):
        self._find_bar.show_and_focus()

    def export_pdf(self, path: str):
        if not self._edit.toPlainText().strip():
            raise ValueError('저장할 내용을 먼저 입력하세요.')
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(self._page_size_id))
        writer.setPageOrientation(self._orientation)
        writer.setResolution(96)
        m = self._margin_mm
        writer.setPageMargins(QMarginsF(m, m, m, m), QPageLayout.Unit.Millimeter)
        doc = self._edit.document().clone()
        pr = writer.pageLayout().paintRectPixels(writer.resolution())
        doc.setPageSize(QSizeF(pr.width(), pr.height()))
        doc.print_(writer)
        self._edit.document().setModified(False)

    # ── 글자 서식 ────────────────────────────────────────────────────────────

    def _merge(self, fmt: QTextCharFormat):
        """mergeCurrentCharFormat 중 시그널 재진입 차단."""
        if self._inhibit_sync:
            return
        self._inhibit_sync = True
        try:
            self._edit.mergeCurrentCharFormat(fmt)
        except Exception:
            swallowed()
        finally:
            self._inhibit_sync = False
        self._edit.setFocus()

    def _apply_bold(self, on: bool):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        self._merge(fmt)

    def _apply_italic(self, on: bool):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        fmt.setFontItalic(on)
        self._merge(fmt)

    def _apply_underline(self, on: bool):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        fmt.setFontUnderline(on)
        self._merge(fmt)

    def _apply_strikeout(self, on: bool):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(on)
        self._merge(fmt)

    def _apply_valign(self, on: bool, is_super: bool):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        if on:
            fmt.setVerticalAlignment(
                QTextCharFormat.VerticalAlignment.AlignSuperScript if is_super
                else QTextCharFormat.VerticalAlignment.AlignSubScript)
            other = self._btn_sub if is_super else self._btn_super
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        self._merge(fmt)

    def _apply_font_family(self, font: QFont):
        if self._inhibit_sync:
            return
        fmt = QTextCharFormat()
        fmt.setFontFamily(font.family())
        self._merge(fmt)

    def _apply_font_size(self, size: int):
        if self._inhibit_sync or size < 1:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(size))
        self._merge(fmt)

    def _choose_font_dialog(self):
        if self._inhibit_sync:
            return
        try:
            base_font = self._edit.currentCharFormat().font()
        except Exception:
            base_font = QFont(self._base_font)
        if not base_font.family():
            base_font = QFont(self._base_font)
        font, ok = QFontDialog.getFont(base_font, self, '\uae00\uaf34 \uc120\ud0dd')
        if not ok:
            return

        fmt = QTextCharFormat()
        if font.family():
            fmt.setFontFamily(font.family())
        if font.pointSize() > 0:
            fmt.setFontPointSize(float(font.pointSize()))
        self._merge(fmt)

        self._font_combo.blockSignals(True)
        try:
            self._font_combo.setCurrentFont(font)
        finally:
            self._font_combo.blockSignals(False)

        if font.pointSize() > 0:
            self._size_sb.blockSignals(True)
            try:
                self._size_sb.setValue(font.pointSize())
            finally:
                self._size_sb.blockSignals(False)

    def _pick_text_color(self):
        col = QColorDialog.getColor(self._text_color, self, '글자 색상')
        if col.isValid():
            self._text_color = col
            fmt = QTextCharFormat()
            fmt.setForeground(col)
            self._merge(fmt)
            self._refresh_color_btn()

    def _pick_highlight(self):
        col = QColorDialog.getColor(self._hl_color, self, '형광펜 색상')
        if col.isValid():
            self._hl_color = col
            fmt = QTextCharFormat()
            fmt.setBackground(col)
            self._merge(fmt)

    def _clear_highlight(self):
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(Qt.GlobalColor.transparent))
        self._merge(fmt)

    def _refresh_color_btn(self):
        c = self._text_color.name()
        self._btn_color.setStyleSheet(
            f'QPushButton{{padding:0 6px;border:1px solid #bbb;border-radius:3px;'
            f'border-bottom:3px solid {c};background:transparent;font-size:13px;'
            f'font-weight:bold;}}'
            f'QPushButton:hover{{background:#e9ecef;}}')

    # ── 단락 서식 ────────────────────────────────────────────────────────────

    def _set_alignment(self, align: Qt.AlignmentFlag):
        self._edit.setAlignment(align)
        self._inhibit_sync = True
        for btn, val in zip(self._align_btns, self._align_vals):
            btn.setChecked(val == align)
        self._inhibit_sync = False
        self._edit.setFocus()

    def _toggle_bullet(self):
        cursor = self._edit.textCursor()
        lst = cursor.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDisc:
            cursor.setBlockFormat(QTextBlockFormat())
            self._btn_bul.setChecked(False)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(QTextListFormat.Style.ListDisc)
            fmt.setIndent(1)
            cursor.createList(fmt)
            self._btn_num.blockSignals(True)
            self._btn_num.setChecked(False)
            self._btn_num.blockSignals(False)
        self._edit.setFocus()

    def _toggle_numbered(self):
        cursor = self._edit.textCursor()
        lst = cursor.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDecimal:
            cursor.setBlockFormat(QTextBlockFormat())
            self._btn_num.setChecked(False)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(QTextListFormat.Style.ListDecimal)
            fmt.setIndent(1)
            cursor.createList(fmt)
            self._btn_bul.blockSignals(True)
            self._btn_bul.setChecked(False)
            self._btn_bul.blockSignals(False)
        self._edit.setFocus()

    def _indent_more(self):
        cur = self._edit.textCursor()
        lst = cur.currentList()
        if lst:
            lf = lst.format(); lf.setIndent(lf.indent() + 1); lst.setFormat(lf)
        else:
            bf = cur.blockFormat(); bf.setIndent(bf.indent() + 1); cur.setBlockFormat(bf)
        self._edit.setFocus()

    def _indent_less(self):
        cur = self._edit.textCursor()
        lst = cur.currentList()
        if lst:
            lf = lst.format(); lf.setIndent(max(1, lf.indent() - 1)); lst.setFormat(lf)
        else:
            bf = cur.blockFormat(); bf.setIndent(max(0, bf.indent() - 1)); cur.setBlockFormat(bf)
        self._edit.setFocus()

    def _apply_style(self, style_name: str):
        if self._inhibit_sync or style_name not in self._STYLES:
            return
        self._inhibit_sync = True
        try:
            pt, bold, level, kind = self._STYLES[style_name]

            # ── 블록 포맷 ────────────────────────────────────────────
            bf = QTextBlockFormat()
            bf.setHeadingLevel(level)
            if kind == 'heading':
                bf.setTopMargin(10.0 if level <= 2 else 5.0)
                bf.setBottomMargin(4.0)
                bf.setBackground(QColor(Qt.GlobalColor.transparent))
                bf.setLeftMargin(0.0)
            elif kind == 'code':
                bf.setBackground(QColor('#f4f4f4'))
                bf.setLeftMargin(12.0)
                bf.setTopMargin(4.0); bf.setBottomMargin(4.0)
            elif kind == 'quote':
                bf.setBackground(QColor('#fafafa'))
                bf.setLeftMargin(20.0)
                bf.setTopMargin(4.0); bf.setBottomMargin(4.0)
            else:
                bf.setBackground(QColor(Qt.GlobalColor.transparent))
                bf.setLeftMargin(0.0)
                bf.setTopMargin(0.0); bf.setBottomMargin(0.0)

            # ── 글자 포맷 ────────────────────────────────────────────
            cf = QTextCharFormat()
            if pt > 0:
                cf.setFontPointSize(float(pt))
            cf.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            if kind == 'code':
                cf.setFontFamily('Consolas')
                cf.setFontPointSize(11.0)
                cf.setForeground(QColor('#333333'))
                cf.setFontItalic(False)
            elif kind == 'quote':
                cf.setFontItalic(True)
                cf.setForeground(QColor('#555555'))
            elif kind == 'subtitle':
                cf.setForeground(QColor('#444444'))
                cf.setFontItalic(False)
            else:
                cf.setFontItalic(False)
                cf.setForeground(QColor('#000000'))

            # ── 커서 조작: beginEditBlock 으로 원자적 처리 ───────────
            cursor = self._edit.textCursor()
            cursor.beginEditBlock()
            try:
                # 현재 단락 전체 선택
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.setBlockFormat(bf)
                # setBlockFormat 후 커서를 에디터에 반영한 뒤
                # 에디터 API로 글자 포맷 적용 (구식 cursor 객체 재사용 금지)
                self._edit.setTextCursor(cursor)
                self._edit.mergeCurrentCharFormat(cf)
            finally:
                cursor.endEditBlock()
        except Exception:
            swallowed()
        finally:
            self._inhibit_sync = False
        self._edit.setFocus()

    def _apply_line_spacing(self, idx: int):
        if self._inhibit_sync:
            return
        pcts = [100.0, 115.0, 150.0, 200.0, 250.0]
        pct = pcts[min(idx, len(pcts) - 1)]
        cursor = self._edit.textCursor()
        if not cursor.hasSelection():
            bf = cursor.blockFormat()
            bf.setLineHeight(pct, _PROPORTIONAL)
            cursor.setBlockFormat(bf)
        else:
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            cursor.setPosition(start)
            while cursor.position() <= end:
                bf = cursor.blockFormat()
                bf.setLineHeight(pct, _PROPORTIONAL)
                cursor.setBlockFormat(bf)
                if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                    break
        self._edit.setFocus()

    # ── 삽입 ────────────────────────────────────────────────────────────────

    def _insert_table(self):
        dlg = _TableDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rows, cols = dlg.values()
        cursor = self._edit.textCursor()
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderStyle(QTextTableFormat.BorderStyle.BorderStyle_Solid)
        tf.setCellPadding(5)
        tf.setCellSpacing(0)
        tf.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        cursor.insertTable(rows, cols, tf)
        self._edit.setFocus()

    def _insert_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '이미지 삽입', '',
            '이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;모든 파일 (*)')
        if not path:
            return
        cursor = self._edit.textCursor()
        fmt = QTextImageFormat()
        fmt.setName(QUrl.fromLocalFile(path).toString())
        fmt.setWidth(370.0)
        cursor.insertImage(fmt)
        self._edit.setFocus()

    def _insert_hr(self):
        self._edit.textCursor().insertHtml(
            '<hr style="border:0;border-top:2px solid #aaa;margin:6px 0;"/>')
        self._edit.setFocus()

    def _insert_page_break(self):
        cursor = self._edit.textCursor()
        bf = QTextBlockFormat()
        bf.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        cursor.insertBlock(bf)
        self._edit.setFocus()

    def _insert_date(self):
        from datetime import date
        self._edit.textCursor().insertText(date.today().strftime('%Y년 %m월 %d일'))
        self._edit.setFocus()

    # ── 페이지 설정 ──────────────────────────────────────────────────────────

    def _show_page_setup(self):
        dlg = _PageSetupDialog(
            self._page_size_id, self._orientation, self._margin_mm, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._page_size_id, self._orientation, self._margin_mm = dlg.values()

    # ── 내보내기 ────────────────────────────────────────────────────────────

    def _export_html(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'HTML로 저장', '', 'HTML 파일 (*.html *.htm)')
        if not path:
            return
        if not path.lower().endswith(('.html', '.htm')):
            path += '.html'
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._edit.toHtml())
            QMessageBox.information(self, '저장 완료', f'HTML 저장:\n{path}')
        except Exception as e:
            QMessageBox.warning(self, '저장 실패', str(e))

    def _export_txt(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'TXT로 저장', '', '텍스트 파일 (*.txt)')
        if not path:
            return
        if not path.lower().endswith('.txt'):
            path += '.txt'
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._edit.toPlainText())
            QMessageBox.information(self, '저장 완료', f'TXT 저장:\n{path}')
        except Exception as e:
            QMessageBox.warning(self, '저장 실패', str(e))

    # ── 툴바 ↔ 커서 동기화 ──────────────────────────────────────────────────

    def _sync_toolbar_from_cursor(self):
        """커서 위치의 실제 서식으로 툴바 상태를 갱신."""
        try:
            fmt = self._edit.currentCharFormat()
            self._on_char_format_changed(fmt)
        except Exception:
            swallowed()

    def _on_char_format_changed(self, fmt: QTextCharFormat):
        if self._inhibit_sync:
            return
        # currentCharFormatChanged 는 Qt 내부에서 const-ref 로 전달되므로
        # PySide6 래퍼가 임시 C++ 객체를 참조할 수 있음.
        # 에디터에서 직접 안전한 사본을 가져와 access violation 방지.
        try:
            fmt = self._edit.currentCharFormat()
        except Exception:
            return
        self._inhibit_sync = True
        try:
            w = fmt.fontWeight()
            # PySide6 버전에 따라 int 또는 enum 반환 — 모두 int 로 비교
            bold_val = int(w.value if hasattr(w, 'value') else w)
            self._btn_bold.setChecked(bold_val >= 700)
            self._btn_italic.setChecked(fmt.fontItalic())
            self._btn_under.setChecked(fmt.fontUnderline())
            self._btn_strike.setChecked(fmt.fontStrikeOut())

            va = fmt.verticalAlignment()
            self._btn_super.setChecked(
                va == QTextCharFormat.VerticalAlignment.AlignSuperScript)
            self._btn_sub.setChecked(
                va == QTextCharFormat.VerticalAlignment.AlignSubScript)

            # fontFamily() 는 Qt 6 내부에서 heading 블록의 font CSS resolve 시
            # Windows DirectWrite/COM 을 경유해 0x8001010d → access violation 유발.
            # fmt.font().family() 는 QFont 의 단순 문자열 반환으로 안전.
            _fam = fmt.font().family()
            if _fam:
                def _set_font(f=_fam):
                    self._font_combo.blockSignals(True)
                    try:
                        self._font_combo.setCurrentFont(QFont(f))
                    except Exception:
                        swallowed()
                    finally:
                        self._font_combo.blockSignals(False)
                QTimer.singleShot(30, _set_font)

            sz = fmt.fontPointSize()
            if sz > 0:
                self._size_sb.blockSignals(True)
                try:
                    self._size_sb.setValue(int(sz))
                except Exception:
                    swallowed()
                finally:
                    self._size_sb.blockSignals(False)
        except Exception:
            swallowed()
        finally:
            self._inhibit_sync = False

    def _on_cursor_changed(self):
        if self._inhibit_sync:
            return
        try:
            cur = self._edit.textCursor()
            row = cur.blockNumber() + 1
            col = cur.positionInBlock() + 1
            self.cursor_changed.emit(row, col)
            self._lbl_cursor.setText(f'{row}행 {col}열')

            self._inhibit_sync = True
            try:
                align = self._edit.alignment()
                for btn, val in zip(self._align_btns, self._align_vals):
                    btn.setChecked(val == align)

                lst = cur.currentList()
                if lst:
                    style = lst.format().style()
                    self._btn_bul.setChecked(style == QTextListFormat.Style.ListDisc)
                    self._btn_num.setChecked(style == QTextListFormat.Style.ListDecimal)
                else:
                    self._btn_bul.setChecked(False)
                    self._btn_num.setChecked(False)
            finally:
                self._inhibit_sync = False
        except Exception:
            swallowed()

    def _schedule_stats(self):
        """contentsChanged 는 문서 수정 중에 발생 → QTimer 로 지연해서 안전하게 처리."""
        QTimer.singleShot(0, self._update_stats)

    def _update_stats(self):
        try:
            text  = self._edit.toPlainText()
            chars = len(text)
            words = len(text.split()) if text.strip() else 0
            lines = text.count('\n') + 1 if text else 0
            self._lbl_chars.setText(f'글자: {chars:,}')
            self._lbl_words.setText(f'단어: {words:,}')
            self._lbl_lines.setText(f'줄: {lines:,}')
        except Exception:
            swallowed()
