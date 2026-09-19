# ui/dialogs/export_image_dialog.py — 이미지로 내보내기
from __future__ import annotations
import os
import fitz
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSpinBox, QPushButton, QFileDialog, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt


class ExportImageDialog(QDialog):
    def __init__(self, doc, current_page: int, parent=None):
        super().__init__(parent)
        self._doc  = doc
        self._page = current_page
        self.setWindowTitle('이미지로 내보내기')
        self.setMinimumWidth(360)

        ly = QVBoxLayout(self)

        # 범위
        rng_ly = QHBoxLayout()
        rng_ly.addWidget(QLabel('범위:'))
        self._range_cb = QComboBox()
        self._range_cb.addItems(['현재 페이지', '전체 페이지'])
        rng_ly.addWidget(self._range_cb)
        ly.addLayout(rng_ly)

        # 형식
        fmt_ly = QHBoxLayout()
        fmt_ly.addWidget(QLabel('형식:'))
        self._fmt_cb = QComboBox()
        self._fmt_cb.addItems(['PNG', 'JPEG'])
        fmt_ly.addWidget(self._fmt_cb)
        ly.addLayout(fmt_ly)

        # DPI
        dpi_ly = QHBoxLayout()
        dpi_ly.addWidget(QLabel('DPI:'))
        self._dpi_sb = QSpinBox()
        self._dpi_sb.setRange(72, 600)
        self._dpi_sb.setValue(150)
        dpi_ly.addWidget(self._dpi_sb)
        ly.addLayout(dpi_ly)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)

    def export(self):
        fmt = self._fmt_cb.currentText().lower()
        dpi = self._dpi_sb.value()
        zoom = dpi / 72
        mat  = fitz.Matrix(zoom, zoom)

        if self._range_cb.currentIndex() == 0:
            pages = [self._page]
        else:
            pages = list(range(self._doc.page_count()))

        if len(pages) == 1:
            path, _ = QFileDialog.getSaveFileName(
                self, '저장 경로', '', f'{fmt.upper()} (*.{fmt})')
            if not path:
                return
            pix = self._doc.fitz_page(pages[0]).get_pixmap(matrix=mat)
            if fmt == 'png':
                pix.save(path)
            else:
                pix.save(path, 'jpeg')
        else:
            folder = QFileDialog.getExistingDirectory(self, '저장 폴더')
            if not folder:
                return
            for i in pages:
                pix = self._doc.fitz_page(i).get_pixmap(matrix=mat)
                fname = os.path.join(folder, f'page_{i+1:04d}.{fmt}')
                if fmt == 'png':
                    pix.save(fname)
                else:
                    pix.save(fname, 'jpeg')
