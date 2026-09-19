# ui/dialogs/simple_text_editor.py — 독립 텍스트 에디터 (메모장 스타일)
from __future__ import annotations
import os
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (QAction, QKeySequence, QFont, QTextCursor,
                            QTextDocument, QIcon)
from PySide6.QtWidgets import (
    QMainWindow, QPlainTextEdit, QFileDialog, QMessageBox,
    QStatusBar, QLabel, QFontDialog, QDialog, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QCheckBox, QToolBar,
    QWidget,
)


class _FindBar(QWidget):
    """하단 찾기 바."""

    def __init__(self, editor: 'SimpleTextEditor'):
        super().__init__(editor)
        self._editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText('찾기…')
        self._input.setFixedWidth(220)
        self._input.returnPressed.connect(self._find_next)
        lay.addWidget(self._input)

        self._case_cb = QCheckBox('대/소문자')
        lay.addWidget(self._case_cb)

        btn_prev = QPushButton('◀')
        btn_prev.setFixedWidth(32)
        btn_prev.setToolTip('이전 (Shift+Enter)')
        btn_prev.clicked.connect(self._find_prev)
        lay.addWidget(btn_prev)

        btn_next = QPushButton('▶')
        btn_next.setFixedWidth(32)
        btn_next.setToolTip('다음 (Enter)')
        btn_next.clicked.connect(self._find_next)
        lay.addWidget(btn_next)

        self._info = QLabel('')
        self._info.setStyleSheet('color: #888; font-size: 11px;')
        lay.addWidget(self._info)

        lay.addStretch()

        close_btn = QPushButton('✕')
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)

        self.setStyleSheet(
            'QWidget { background: #f0f0f0; border-top: 1px solid #ccc; }')
        self.hide()

    def show_and_focus(self):
        self.show()
        self._input.setFocus()
        self._input.selectAll()

    def _find(self, backward: bool = False):
        text = self._input.text()
        if not text:
            return
        ed = self._editor._edit
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self._case_cb.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        found = ed.find(text, flags)
        if not found:
            # 처음(또는 끝)으로 되감기
            cur = ed.textCursor()
            cur.movePosition(
                QTextCursor.MoveOperation.End if backward
                else QTextCursor.MoveOperation.Start)
            ed.setTextCursor(cur)
            found = ed.find(text, flags)
        self._info.setText('찾을 수 없음' if not found else '')

    def _find_next(self):
        self._find(backward=False)

    def _find_prev(self):
        self._find(backward=True)


class SimpleTextEditor(QMainWindow):
    """기본 텍스트 에디터 창 (메모장 + 찾기 + 글꼴)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str = ''
        self._last_dir: str = str(Path.home())
        self._setui()
        self._update_title()
        self.resize(800, 600)

    def _setui(self):
        # ── 에디터 ────────────────────────────────────────────────────
        self._edit = QPlainTextEdit()
        self._edit.setFont(QFont('Malgun Gothic', 11))
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edit.document().modificationChanged.connect(self._update_title)
        self._edit.cursorPositionChanged.connect(self._update_status)

        # ── 찾기 바 ───────────────────────────────────────────────────
        self._find_bar = _FindBar(self)

        # ── 중앙 위젯 (에디터 + 찾기 바) ─────────────────────────────
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)
        vlay.addWidget(self._edit)
        vlay.addWidget(self._find_bar)
        self.setCentralWidget(container)

        # ── 메뉴 ──────────────────────────────────────────────────────
        mb = self.menuBar()

        # 파일
        fm = mb.addMenu('파일(&F)')
        self._act(fm, '새로 만들기(&N)',  self._new,     'Ctrl+N')
        self._act(fm, '열기(&O)…',       self._open,    'Ctrl+O')
        fm.addSeparator()
        self._act(fm, '저장(&S)',         self._save,    'Ctrl+S')
        self._act(fm, '다른 이름으로 저장…', self._save_as, 'Ctrl+Shift+S')
        fm.addSeparator()
        self._act(fm, '닫기',             self.close)

        # 편집
        em = mb.addMenu('편집(&E)')
        self._act(em, '실행 취소',  self._edit.undo,      'Ctrl+Z')
        self._act(em, '다시 실행',  self._edit.redo,      'Ctrl+Y')
        em.addSeparator()
        self._act(em, '잘라내기',   self._edit.cut,       'Ctrl+X')
        self._act(em, '복사',       self._edit.copy,      'Ctrl+C')
        self._act(em, '붙여넣기',   self._edit.paste,     'Ctrl+V')
        self._act(em, '모두 선택',  self._edit.selectAll, 'Ctrl+A')
        em.addSeparator()
        self._act(em, '찾기…',      self._show_find,      'Ctrl+F')

        # 서식
        fmt = mb.addMenu('서식(&O)')
        self._act(fmt, '글꼴…',             self._choose_font)
        ww_act = QAction('자동 줄 바꿈', self, checkable=True, checked=True)
        ww_act.triggered.connect(self._toggle_wrap)
        fmt.addAction(ww_act)

        # ── 상태바 ────────────────────────────────────────────────────
        self._pos_lbl = QLabel('줄 1, 열 1')
        self._pos_lbl.setStyleSheet('padding: 0 8px;')
        self.statusBar().addPermanentWidget(self._pos_lbl)

    def _act(self, menu, text, slot, shortcut=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ── 파일 동작 ──────────────────────────────────────────────────────
    def _new(self):
        if not self._confirm_discard():
            return
        self._edit.setPlainText('')
        self._edit.document().setModified(False)
        self._path = ''
        self._update_title()

    def _open(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '파일 열기', self._last_dir,
            '텍스트 파일 (*.txt *.md *.csv *.log *.py *.js *.html *.css *.json *.xml);;'
            '모든 파일 (*)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                self._edit.setPlainText(f.read())
            self._edit.document().setModified(False)
            self._path = path
            self._last_dir = str(Path(path).parent)
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, '열기 오류', f'파일을 열 수 없습니다:\n{e}')

    def _save(self):
        if not self._path:
            self._save_as()
        else:
            self._write(self._path)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '다른 이름으로 저장', self._last_dir,
            '텍스트 파일 (*.txt);;모든 파일 (*)')
        if path:
            self._write(path)
            self._path = path
            self._last_dir = str(Path(path).parent)
            self._update_title()

    def _write(self, path: str):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._edit.toPlainText())
            self._edit.document().setModified(False)
            self._update_title()
            self.statusBar().showMessage(f'저장됨: {path}', 3000)
        except Exception as e:
            QMessageBox.critical(self, '저장 오류', f'저장에 실패했습니다:\n{e}')

    # ── 서식 ──────────────────────────────────────────────────────────
    def _choose_font(self):
        font, ok = QFontDialog.getFont(self._edit.font(), self)
        if ok:
            self._edit.setFont(font)

    def _toggle_wrap(self, checked: bool):
        mode = (QPlainTextEdit.LineWrapMode.WidgetWidth if checked
                else QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.setLineWrapMode(mode)

    # ── 찾기 ──────────────────────────────────────────────────────────
    def _show_find(self):
        self._find_bar.show_and_focus()

    # ── 상태 / 타이틀 ─────────────────────────────────────────────────
    def _update_title(self):
        name = Path(self._path).name if self._path else '새 문서'
        mod  = ' *' if self._edit.document().isModified() else ''
        self.setWindowTitle(f'{name}{mod} — 텍스트 에디터')

    def _update_status(self):
        cur  = self._edit.textCursor()
        line = cur.blockNumber() + 1
        col  = cur.positionInBlock() + 1
        self._pos_lbl.setText(f'줄 {line}, 열 {col}')

    # ── 닫기 확인 ─────────────────────────────────────────────────────
    def _confirm_discard(self) -> bool:
        if not self._edit.document().isModified():
            return True
        ans = QMessageBox.question(
            self, '저장되지 않은 변경사항',
            '변경사항이 있습니다. 저장하시겠습니까?',
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Save:
            self._save()
            return not self._edit.document().isModified()
        return ans == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
