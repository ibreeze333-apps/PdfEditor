# ui/canvas_scene.py — PdfCanvasScene
from __future__ import annotations
from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtCore import Qt


class PdfCanvasScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
