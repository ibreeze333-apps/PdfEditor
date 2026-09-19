# ui/dialogs/header_footer_dialog.py — 머리글/바닥글 + 페이지 번호
from __future__ import annotations
import fitz
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QDialogButtonBox, QGroupBox,
)


class HeaderFooterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('머리글 / 바닥글')
        self.setMinimumWidth(420)

        ly = QVBoxLayout(self)

        # ── 머리글 ──
        hdr_box = QGroupBox('머리글')
        hdr_ly  = QVBoxLayout(hdr_box)
        self._hdr_chk = QCheckBox('머리글 추가')
        hdr_ly.addWidget(self._hdr_chk)
        ht_ly = QHBoxLayout()
        ht_ly.addWidget(QLabel('텍스트:'))
        self._hdr_ed = QLineEdit()
        self._hdr_ed.setPlaceholderText('{page} = 페이지 번호 자동 삽입')
        ht_ly.addWidget(self._hdr_ed)
        hdr_ly.addLayout(ht_ly)
        hm_ly = QHBoxLayout()
        hm_ly.addWidget(QLabel('여백(pt):'))
        self._hdr_margin = QSpinBox()
        self._hdr_margin.setRange(10, 100)
        self._hdr_margin.setValue(30)
        hm_ly.addWidget(self._hdr_margin)
        hdr_ly.addLayout(hm_ly)
        ly.addWidget(hdr_box)

        # ── 바닥글 ──
        ftr_box = QGroupBox('바닥글')
        ftr_ly  = QVBoxLayout(ftr_box)
        self._ftr_chk = QCheckBox('바닥글 추가')
        ftr_ly.addWidget(self._ftr_chk)
        ft_ly = QHBoxLayout()
        ft_ly.addWidget(QLabel('텍스트:'))
        self._ftr_ed = QLineEdit('{page} / {total}')
        self._ftr_ed.setPlaceholderText('{page} = 페이지 번호, {total} = 전체')
        ft_ly.addWidget(self._ftr_ed)
        ftr_ly.addLayout(ft_ly)
        fm_ly = QHBoxLayout()
        fm_ly.addWidget(QLabel('여백(pt):'))
        self._ftr_margin = QSpinBox()
        self._ftr_margin.setRange(10, 100)
        self._ftr_margin.setValue(20)
        fm_ly.addWidget(self._ftr_margin)
        ftr_ly.addLayout(fm_ly)
        ly.addWidget(ftr_box)

        # ── 공통 설정 ──
        fs_ly = QHBoxLayout()
        fs_ly.addWidget(QLabel('폰트 크기:'))
        self._font_sb = QSpinBox()
        self._font_sb.setRange(6, 36)
        self._font_sb.setValue(10)
        fs_ly.addWidget(self._font_sb)
        ly.addLayout(fs_ly)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    @staticmethod
    def apply(fitz_doc, hdr_text: str | None, ftr_text: str | None,
              hdr_margin: int, ftr_margin: int, font_size: int):
        total = fitz_doc.page_count
        for i in range(total):
            page = fitz_doc[i]
            w    = page.rect.width
            h    = page.rect.height
            num  = i + 1

            if hdr_text:
                txt = hdr_text.replace('{page}', str(num)).replace('{total}', str(total))
                page.insert_text(
                    fitz.Point(w / 2 - len(txt) * font_size * 0.3, hdr_margin),
                    txt, fontsize=font_size, color=(0, 0, 0))

            if ftr_text:
                txt = ftr_text.replace('{page}', str(num)).replace('{total}', str(total))
                page.insert_text(
                    fitz.Point(w / 2 - len(txt) * font_size * 0.3, h - ftr_margin),
                    txt, fontsize=font_size, color=(0, 0, 0))

    def header_text(self) -> str | None:
        return self._hdr_ed.text().strip() if self._hdr_chk.isChecked() else None

    def footer_text(self) -> str | None:
        return self._ftr_ed.text().strip() if self._ftr_chk.isChecked() else None

    def hdr_margin(self) -> int:  return self._hdr_margin.value()
    def ftr_margin(self) -> int:  return self._ftr_margin.value()
    def font_size(self)  -> int:  return self._font_sb.value()
