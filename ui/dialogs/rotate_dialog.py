# ui/dialogs/rotate_dialog.py — 페이지 회전 범위 선택
"""회전할 페이지를 고르는 작은 대화상자.

현재 페이지 / 페이지 지정(1-5, 7 처럼) / 문서 전체 중에서 고른다. 기본값은
현재 페이지이므로 Enter 만 눌러도 예전처럼 한 장만 회전된다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QLineEdit,
    QDialogButtonBox, QButtonGroup, QWidget,
)


def parse_page_list(raw: str, page_count: int) -> list[int]:
    """'1-5, 8, 12-10' 같은 입력을 0-based 페이지 번호 목록으로 바꾼다.

    - 범위가 거꾸로 적혀도(12-10) 받아들인다.
    - 문서 범위를 벗어난 번호는 버린다.
    - 중복은 한 번만, 순서는 오름차순.
    잘못된 조각은 조용히 무시한다(사용자가 오타를 냈다고 전체를 실패시키지 않음).
    """
    out: set[int] = set()
    for part in (raw or '').replace(' ', '').split(','):
        if not part:
            continue
        if '-' in part[1:]:            # 앞자리 음수 표기는 무시
            a, _, b = part.partition('-')
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                for p in range(lo, hi + 1):
                    if 1 <= p <= page_count:
                        out.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= page_count:
                out.add(p - 1)
    return sorted(out)


class RotateDialog(QDialog):
    """회전 범위 선택. exec() 가 참이면 pages() 로 대상 페이지를 얻는다."""

    def __init__(self, parent=None, *, title: str = '페이지 회전',
                 page_count: int = 1, current_page: int = 0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._page_count = max(1, int(page_count))
        self._current = max(0, min(int(current_page), self._page_count - 1))

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'회전할 페이지를 고르세요  (전체 {self._page_count}쪽)'))

        self._rb_cur = QRadioButton(f'현재 페이지만  ({self._current + 1}쪽)')
        self._rb_sel = QRadioButton('페이지 지정')
        self._rb_all = QRadioButton(f'문서 전체  ({self._page_count}쪽)')
        self._rb_cur.setChecked(True)
        grp = QButtonGroup(self)
        for rb in (self._rb_cur, self._rb_sel, self._rb_all):
            grp.addButton(rb)
        lay.addWidget(self._rb_cur)

        row = QWidget(); rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._rb_sel)
        self._ed = QLineEdit()
        self._ed.setPlaceholderText('예: 1-5, 8, 12-15')
        self._ed.setEnabled(False)
        self._ed.setClearButtonEnabled(True)
        rl.addWidget(self._ed, 1)
        lay.addWidget(row)
        lay.addWidget(self._rb_all)

        self._hint = QLabel('')
        self._hint.setStyleSheet('color:#a60;')
        lay.addWidget(self._hint)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel, self)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)

        self._rb_sel.toggled.connect(self._on_mode)
        self._ed.textChanged.connect(self._update_hint)
        self.resize(360, 190)

    # ── 내부 ─────────────────────────────────────────────────────────
    def _on_mode(self, on: bool):
        self._ed.setEnabled(on)
        if on:
            self._ed.setFocus()
        self._update_hint()

    def _update_hint(self):
        if not self._rb_sel.isChecked():
            self._hint.setText('')
            return
        pages = parse_page_list(self._ed.text(), self._page_count)
        raw = self._ed.text().strip()
        if not raw:
            self._hint.setText('회전할 페이지 번호를 입력하세요.')
        elif not pages:
            self._hint.setText('해당하는 페이지가 없습니다.')
        else:
            self._hint.setText(f'{len(pages)}쪽 선택됨')

    def _on_ok(self):
        if self._rb_sel.isChecked() and not self.pages():
            self._update_hint()
            self._ed.setFocus()
            return          # 유효한 페이지가 없으면 닫지 않는다
        self.accept()

    # ── 결과 ─────────────────────────────────────────────────────────
    def pages(self) -> list[int]:
        """회전할 페이지(0-based) 목록."""
        if self._rb_all.isChecked():
            return list(range(self._page_count))
        if self._rb_sel.isChecked():
            return parse_page_list(self._ed.text(), self._page_count)
        return [self._current]
