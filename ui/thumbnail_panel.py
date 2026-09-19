# ui/thumbnail_panel.py — 좌측 썸네일 패널
# fitz는 스레드 안전하지 않으므로 백그라운드 스레드 사용 금지.
# QTimer.singleShot(0, ...)으로 메인 스레드에서 1장씩 렌더링한다.
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from utils.fitz_qt_bridge import render_page


class ThumbnailPanel(QListWidget):
    page_selected = Signal(int)

    THUMB_W = 110

    def __init__(self, doc, renderer, parent=None):
        super().__init__(parent)
        self._doc        = doc
        self._renderer   = renderer   # 호환성 유지 (사용하지 않음)
        self._generation = 0          # reload() 때마다 증가 → 이전 세대 무시

        from PySide6.QtCore import QSize
        self.setIconSize(QSize(self.THUMB_W, 160))
        self.setSpacing(4)
        self.setFixedWidth(self.THUMB_W + 36)
        self.itemClicked.connect(
            lambda item: self.page_selected.emit(item.data(Qt.ItemDataRole.UserRole)))

    def reload(self):
        self._generation += 1
        gen = self._generation
        self.clear()
        if not self._doc.is_open:
            return
        # 먼저 텍스트 아이템(페이지 번호)을 모두 추가
        for i in range(self._doc.page_count()):
            item = QListWidgetItem(f'  {i + 1}')
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.addItem(item)
        # 첫 번째 썸네일 렌더를 이벤트 루프에 위임
        QTimer.singleShot(0, lambda: self._render_next(0, gen))

    def _render_next(self, index: int, gen: int):
        """메인 스레드에서 1페이지씩 순차 렌더링. 이벤트 루프가 그 사이 UI 갱신 처리."""
        if gen != self._generation:
            return   # 더 최신 reload()가 시작됐으면 이 세대는 중단
        if not self._doc.is_open:
            return
        n = self._doc.page_count()
        if index >= n:
            return   # 모든 페이지 완료

        item = self.item(index)
        if item is not None:
            try:
                page = self._doc.fitz_page(index)
                pw   = page.rect.width
                zoom = self.THUMB_W / max(1.0, pw)
                img  = render_page(page, zoom=zoom)
                pxm  = QPixmap.fromImage(img)
                item.setIcon(QIcon(pxm))
            except Exception as e:
                print(f'[ThumbnailPanel] render error page {index}: {e}')

        # 다음 페이지를 이벤트 루프가 한 번 돈 뒤 렌더링
        QTimer.singleShot(0, lambda: self._render_next(index + 1, gen))

    def highlight(self, index: int):
        self.setCurrentRow(index)
