# ui/dialogs/watermark_dialog.py - 워터마크 설정 창
from __future__ import annotations
import fitz
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QDialogButtonBox,
    QColorDialog, QPushButton, QFileDialog,
)
from PySide6.QtGui import QColor


class WatermarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('워터마크 추가')
        self.setMinimumWidth(420)
        self._color = QColor(128, 128, 128)

        ly = QVBoxLayout(self)

        mode_ly = QHBoxLayout()
        mode_ly.addWidget(QLabel('방식:'))
        self._mode_cb = QComboBox()
        self._mode_cb.addItems(['텍스트', '이미지'])
        self._mode_cb.currentIndexChanged.connect(self._sync_mode_ui)
        mode_ly.addWidget(self._mode_cb)
        ly.addLayout(mode_ly)

        self._text_row = QHBoxLayout()
        self._text_row.addWidget(QLabel('문구:'))
        self._text_ed = QLineEdit('DRAFT')
        self._text_row.addWidget(self._text_ed)
        ly.addLayout(self._text_row)

        self._image_row = QHBoxLayout()
        self._image_row.addWidget(QLabel('이미지:'))
        self._image_ed = QLineEdit('')
        self._browse_btn = QPushButton('찾아보기')
        self._browse_btn.clicked.connect(self._pick_image)
        self._image_row.addWidget(self._image_ed, 1)
        self._image_row.addWidget(self._browse_btn)
        ly.addLayout(self._image_row)

        fs_ly = QHBoxLayout()
        fs_ly.addWidget(QLabel('크기:'))
        self._size_sb = QSpinBox()
        self._size_sb.setRange(10, 200)
        self._size_sb.setValue(60)
        fs_ly.addWidget(self._size_sb)
        ly.addLayout(fs_ly)

        scale_ly = QHBoxLayout()
        scale_ly.addWidget(QLabel('이미지 비율(%):'))
        self._image_scale_sb = QSpinBox()
        self._image_scale_sb.setRange(5, 100)
        self._image_scale_sb.setValue(35)
        scale_ly.addWidget(self._image_scale_sb)
        ly.addLayout(scale_ly)

        op_ly = QHBoxLayout()
        op_ly.addWidget(QLabel('투명도:'))
        self._opacity_sb = QDoubleSpinBox()
        self._opacity_sb.setRange(0.05, 1.0)
        self._opacity_sb.setSingleStep(0.05)
        self._opacity_sb.setValue(0.3)
        op_ly.addWidget(self._opacity_sb)
        ly.addLayout(op_ly)

        ang_ly = QHBoxLayout()
        ang_ly.addWidget(QLabel('각도:'))
        self._angle_sb = QSpinBox()
        self._angle_sb.setRange(-180, 180)
        self._angle_sb.setSingleStep(45)
        self._angle_sb.setValue(45)
        ang_ly.addWidget(self._angle_sb)
        ly.addLayout(ang_ly)

        col_ly = QHBoxLayout()
        col_ly.addWidget(QLabel('색상:'))
        self._col_btn = QPushButton()
        self._col_btn.setFixedWidth(60)
        self._update_color_btn()
        self._col_btn.clicked.connect(self._pick_color)
        col_ly.addWidget(self._col_btn)
        ly.addLayout(col_ly)

        self._image_note = QLabel('이미지 워터마크는 현재 문서의 가운데에 비율을 유지해 배치됩니다.')
        self._image_note.setWordWrap(True)
        self._image_note.setStyleSheet('color: #666; font-size: 12px;')
        ly.addWidget(self._image_note)

        rng_ly = QHBoxLayout()
        rng_ly.addWidget(QLabel('범위:'))
        self._range_cb = QComboBox()
        self._range_cb.addItems(['전체 페이지', '현재 페이지'])
        rng_ly.addWidget(self._range_cb)
        ly.addLayout(rng_ly)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        ly.addWidget(btns)
        self._sync_mode_ui()

    def _update_color_btn(self):
        self._col_btn.setStyleSheet(f'background-color: {self._color.name()};')

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self)
        if c.isValid():
            self._color = c
            self._update_color_btn()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '워터마크 이미지 선택', '',
            '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)')
        if path:
            self._image_ed.setText(path)

    def _sync_mode_ui(self):
        is_text = self.mode() == 'text'
        self._text_ed.setEnabled(is_text)
        self._size_sb.setEnabled(is_text)
        self._col_btn.setEnabled(is_text)
        self._image_ed.setEnabled(not is_text)
        self._browse_btn.setEnabled(not is_text)
        self._image_scale_sb.setEnabled(not is_text)
        self._image_note.setVisible(not is_text)

    def mode(self) -> str:
        return 'text' if self._mode_cb.currentIndex() == 0 else 'image'

    def image_path(self) -> str:
        return self._image_ed.text().strip()

    def image_scale(self) -> float:
        return self._image_scale_sb.value() / 100.0

    def text(self) -> str:
        return self._text_ed.text()

    def font_size(self) -> int:
        return self._size_sb.value()

    def opacity(self) -> float:
        return self._opacity_sb.value()

    def angle(self) -> int:
        return self._angle_sb.value()

    def color(self) -> list:
        return [self._color.redF(), self._color.greenF(), self._color.blueF()]

    def all_pages(self) -> bool:
        return self._range_cb.currentIndex() == 0

    @staticmethod
    def apply_text(fitz_doc, text: str, font_size: int, opacity: float,
                   angle: int, color: list, pages: list[int]):
        for i in pages:
            page = fitz_doc[i]
            rect = page.rect
            pt = fitz.Point(rect.width / 2, rect.height / 2)
            tw = fitz.TextWriter(rect)
            tw.append(pt, text, fontsize=font_size)
            mat = fitz.Matrix(angle)
            tw.write_text(page, color=color, opacity=opacity, morph=(pt, mat))

    @staticmethod
    def apply_image(fitz_doc, image_path: str, scale: float, angle: int,
                    pages: list[int]):
        src = fitz.open(image_path)
        src_rect = src[0].rect
        for i in pages:
            page = fitz_doc[i]
            rect = page.rect
            scale = max(0.05, min(scale, 1.0))
            max_w = rect.width * scale
            max_h = rect.height * scale
            ratio = min(max_w / max(src_rect.width, 1), max_h / max(src_rect.height, 1))
            w = src_rect.width * ratio
            h = src_rect.height * ratio
            dest = fitz.Rect((rect.width - w) / 2, (rect.height - h) / 2,
                             (rect.width + w) / 2, (rect.height + h) / 2)
            page.insert_image(dest, filename=image_path, keep_proportion=True,
                              overlay=True, rotate=(angle % 360), alpha=0)
        src.close()
