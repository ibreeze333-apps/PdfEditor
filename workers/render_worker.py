# workers/render_worker.py — 비동기 페이지 렌더링
from __future__ import annotations
import fitz
from PySide6.QtCore import QRunnable, QObject, Signal
from PySide6.QtGui import QImage
from utils.fitz_qt_bridge import render_page


class RenderSignals(QObject):
    finished = Signal(int, QImage)   # (page_idx, image)
    error    = Signal(int, str)


class RenderWorker(QRunnable):
    def __init__(self, doc, page_idx: int, zoom: float):
        super().__init__()
        self.signals   = RenderSignals()
        self._doc      = doc
        self._page_idx = page_idx
        self._zoom     = zoom
        self.setAutoDelete(True)

    def run(self):
        try:
            page = self._doc.fitz_page(self._page_idx)
            img  = render_page(page, zoom=self._zoom)
            self.signals.finished.emit(self._page_idx, img)
        except Exception as e:
            self.signals.error.emit(self._page_idx, str(e))
