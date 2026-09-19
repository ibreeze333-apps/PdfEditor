"""Modeless, full-resolution snapshot viewer."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene,
)


class _SnapshotView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.fitting = True

    def fit_image(self):
        self.fitting = True
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def original_size(self):
        self.fitting = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.resetTransform()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitting:
            self.fit_image()


class SnapshotPreviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('스냅샷 보기')
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        available = self.screen().availableGeometry()
        self.resize(min(900, int(available.width() * .8)),
                    min(700, int(available.height() * .8)))
        self.setMinimumSize(360, 260)
        root = QVBoxLayout(self)
        self._info = QLabel()
        self._info.setWordWrap(True)
        root.addWidget(self._info)
        self._view = _SnapshotView(self)
        root.addWidget(self._view, 1)
        row = QHBoxLayout()
        fit = QPushButton('창에 맞춤')
        fit.clicked.connect(self._view.fit_image)
        original = QPushButton('원본 크기')
        original.setToolTip('이미지를 축소하지 않고 표시합니다. 큰 이미지는 스크롤하거나 드래그하세요.')
        original.clicked.connect(self._view.original_size)
        close = QPushButton('닫기')
        close.clicked.connect(self.close)
        row.addWidget(fit)
        row.addWidget(original)
        row.addStretch()
        row.addWidget(close)
        root.addLayout(row)

    def set_snapshot(self, pixmap: QPixmap):
        # Keep the full capture, never the 96px thumbnail. Normalise its DPR so
        # original-size mode represents the image's stored pixels consistently.
        image = QPixmap(pixmap)
        image.setDevicePixelRatio(1.0)
        scene = self._view.scene()
        scene.clear()
        scene.addPixmap(image)
        scene.setSceneRect(0, 0, image.width(), image.height())
        self._info.setText(f'{image.width()} × {image.height()} px · 원본 크기에서는 스크롤·드래그로 이동')
        self._view.fit_image()
        QTimer.singleShot(0, self._view.fit_image)
