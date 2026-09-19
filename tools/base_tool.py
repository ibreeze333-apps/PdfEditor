# tools/base_tool.py — BaseTool 추상 클래스 (전략 패턴)
from __future__ import annotations
from abc import ABC, abstractmethod
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QMouseEvent, QKeyEvent
from utils.errlog import swallowed


class BaseTool(ABC):
    name:   str = ''
    label:  str = ''
    cursor: Qt.CursorShape = Qt.CursorShape.ArrowCursor
    shortcut: str = ''

    def activate(self, view) -> None:
        """도구 활성화: 커서 변경 등."""
        view.viewport().setCursor(self.cursor)

    def deactivate(self, view) -> None:
        """도구 비활성화: 임시 아이템 정리."""
        view.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    @abstractmethod
    def on_press(self, pos: QPointF, event: QMouseEvent, view) -> None: ...

    @abstractmethod
    def on_move(self, pos: QPointF, event: QMouseEvent, view) -> None: ...

    @abstractmethod
    def on_release(self, pos: QPointF, event: QMouseEvent, view) -> None: ...

    def on_key(self, event: QKeyEvent, view) -> bool:
        """키 이벤트. True 반환 시 이벤트 소비."""
        return False

    # ── 공통 헬퍼 ────────────────────────────────────────────────────
    @staticmethod
    def _register_undo(view, page_idx: int, annots: list) -> None:
        """배치 직후 어노테이션 xref 목록을 undo 스택에 등록."""
        xrefs = []
        for a in annots:
            try:
                xrefs.append(a.xref)
            except Exception:
                swallowed()
        if xrefs:
            view.doc().push_undo(page_idx, xrefs)
