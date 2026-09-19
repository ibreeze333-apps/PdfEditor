from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSizeF, QMarginsF
from PySide6.QtGui import (
    QAction,
    QFont,
    QKeySequence,
    QTextDocument,
    QPageLayout,
    QPageSize,
    QPdfWriter,
)
from PySide6.QtWidgets import (
    QDialog,
    QFontDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QDialogButtonBox,
)


class NewTextPdfDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._font = QFont('Malgun Gothic', 12)
        self._saved_path = ''
        self.setWindowTitle('새 문서 작성')
        self.resize(900, 700)
        self._build_ui()
        self._apply_font()

    @property
    def saved_path(self) -> str:
        return self._saved_path

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._font_btn = QPushButton('글꼴 선택…')
        self._font_btn.clicked.connect(self._choose_font)
        top.addWidget(self._font_btn)

        top.addWidget(QLabel('크기'))
        self._size_sb = QSpinBox()
        self._size_sb.setRange(6, 72)
        self._size_sb.setValue(self._font.pointSize())
        self._size_sb.valueChanged.connect(self._change_size)
        top.addWidget(self._size_sb)
        top.addWidget(QLabel('pt'))

        self._info = QLabel('새 문서 내용을 입력한 뒤 PDF로 저장하세요.')
        self._info.setStyleSheet('color: #666;')
        top.addWidget(self._info, 1)
        lay.addLayout(top)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText('여기에 문서를 작성하세요.')
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        lay.addWidget(self._edit, 1)

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton('PDF로 저장', QDialogButtonBox.ButtonRole.AcceptRole)
        self._cancel_btn = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._save_btn.clicked.connect(self._save_pdf)
        self._cancel_btn.clicked.connect(self.reject)
        lay.addWidget(buttons)

        save_act = QAction(self)
        save_act.setShortcut(QKeySequence('Ctrl+S'))
        save_act.triggered.connect(self._save_pdf)
        self.addAction(save_act)

    def _apply_font(self):
        font = QFont(self._font)
        font.setPointSize(self._size_sb.value())
        self._font = font
        self._edit.setFont(font)
        self._font_btn.setText(f'글꼴: {font.family()}')

    def _change_size(self, value: int):
        self._font.setPointSize(value)
        self._apply_font()

    def _choose_font(self):
        ok, font = QFontDialog.getFont(self._font, self, '글꼴 선택')
        if not ok:
            return
        if font.pointSize() > 0:
            self._size_sb.setValue(font.pointSize())
        self._font = font
        self._apply_font()

    def _save_pdf(self):
        text = self._edit.toPlainText().rstrip()
        if not text:
            QMessageBox.information(self, '내용 없음', '저장할 텍스트를 먼저 입력하세요.')
            return

        path, _ = QFileDialog.getSaveFileName(self, 'PDF로 저장', '', 'PDF 파일 (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'

        try:
            self._write_pdf(path, text)
        except Exception as e:
            QMessageBox.critical(self, '저장 오류', f'PDF 저장에 실패했습니다.\n{e}')
            return

        self._saved_path = path
        self.accept()

    def _write_pdf(self, path: str, text: str):
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Portrait)
        writer.setResolution(96)
        writer.setDocumentTitle(Path(path).stem)
        writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter)

        doc = QTextDocument()
        doc.setDefaultFont(self._font)
        doc.setPlainText(text)

        page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
        doc.setPageSize(QSizeF(page_rect.width(), page_rect.height()))
        doc.print_(writer)
