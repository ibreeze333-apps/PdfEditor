# ui/dialogs/image_to_pdf_dialog.py — 이미지 → PDF 변환 다이얼로그
from __future__ import annotations
import fitz
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QFileDialog, QLabel, QComboBox,
    QDialogButtonBox, QListWidgetItem, QCheckBox,
)


class ImageToPdfDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('이미지 → PDF 변환')
        self.setMinimumWidth(500)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # 파일 목록
        lay.addWidget(QLabel('변환할 이미지 파일 (순서대로):'))
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        lay.addWidget(self._list)

        # 버튼
        btn_row = QHBoxLayout()
        add_btn = QPushButton('➕ 추가')
        del_btn = QPushButton('🗑 삭제')
        up_btn  = QPushButton('⬆ 위로')
        dn_btn  = QPushButton('⬇ 아래로')
        add_btn.clicked.connect(self._add)
        del_btn.clicked.connect(self._del)
        up_btn.clicked.connect(self._up)
        dn_btn.clicked.connect(self._down)
        for b in (add_btn, del_btn, up_btn, dn_btn):
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        # 옵션
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel('페이지 크기:'))
        self._size_cb = QComboBox()
        self._size_cb.addItems(['원본 크기', 'A4', 'A3', 'Letter'])
        opt_row.addWidget(self._size_cb)
        self._fit_cb = QCheckBox('페이지에 맞게 조정')
        self._fit_cb.setChecked(True)
        opt_row.addWidget(self._fit_cb)
        opt_row.addStretch()
        lay.addLayout(opt_row)

        # 확인/취소
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '이미지 선택', '',
            '이미지 (*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.tif)')
        for p in paths:
            self._list.addItem(QListWidgetItem(p))

    def _del(self):
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _up(self):
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)

    def _down(self):
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)

    def image_paths(self) -> list[str]:
        return [self._list.item(i).text()
                for i in range(self._list.count())]

    def page_size(self) -> tuple[float, float] | None:
        sizes = {
            'A4':     (595, 842),
            'A3':     (842, 1191),
            'Letter': (612, 792),
        }
        return sizes.get(self._size_cb.currentText())

    def fit_to_page(self) -> bool:
        return self._fit_cb.isChecked()

    @staticmethod
    def convert(image_paths: list[str],
                out_path: str,
                page_size: tuple | None = None,
                fit: bool = True):
        doc = fitz.open()
        for img_path in image_paths:
            src = fitz.open(img_path)
            src_rect = src[0].rect
            if page_size and fit:
                w, h = page_size
            else:
                w, h = src_rect.width, src_rect.height
            page = doc.new_page(width=w, height=h)
            if fit and page_size:
                scale = min(w / src_rect.width, h / src_rect.height)
                nw = src_rect.width * scale
                nh = src_rect.height * scale
                x0 = (w - nw) / 2
                y0 = (h - nh) / 2
                dest = fitz.Rect(x0, y0, x0 + nw, y0 + nh)
            else:
                dest = fitz.Rect(0, 0, w, h)
            page.insert_image(dest, filename=img_path)
            src.close()
        doc.save(out_path, garbage=4, deflate=True)
        doc.close()
