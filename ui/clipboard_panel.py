from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTabWidget, QPushButton, QHBoxLayout, QAbstractItemView,
    QMessageBox,
)
from ui.flow_bar import FlowBar
from ui.dialogs.snapshot_preview_dialog import SnapshotPreviewDialog


class ClipboardPanel(QWidget):
    restore_text_requested    = Signal(str)
    restore_image_requested   = Signal(QPixmap)

    # ── 새 시그널 (4가지 기능) ──────────────────────────────────────
    save_snapshot_requested   = Signal(QPixmap)       # 파일로 저장
    insert_pdf_requested      = Signal(QPixmap)       # PDF에 이미지 삽입
    region_capture_requested  = Signal()              # 영역 선택 캡처 시작
    compare_requested         = Signal(list)          # 비교 (snapshot list 전달)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clipboard_items: list[dict] = []
        self._snapshot_items: list[dict] = []
        self._max_items = 30
        self._preview = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._tabs = QTabWidget(self)
        root.addWidget(self._tabs, 1)

        self._snapshot_list  = self._make_list()
        self._snapshot_list.itemClicked.connect(self._preview_item)
        self._clipboard_list = self._make_list()

        self._tabs.addTab(self._snapshot_list,  '스냅샷')
        self._tabs.addTab(self._clipboard_list, '클립보드')

        hint = QLabel('스냅샷 클릭: 새 창에서 보기 · 더블클릭: 클립보드에 복사')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #666; font-size: 11px;')
        root.addWidget(hint)

        # ── 스냅샷 액션 버튼 행 ────────────────────────────────────
        snap_btn_row = FlowBar(self, hspace=4, vspace=4)

        btn_style = (
            'QPushButton { padding: 4px 8px; font-size: 11px; border-radius: 4px;'
            '  border: 1px solid #ccc; background: #f8f8f8; }'
            'QPushButton:hover { background: #e8f0fe; border-color: #4361ee; color: #4361ee; }'
            'QPushButton:pressed { background: #dde4ff; }'
        )

        self._btn_region = QPushButton('✂ 영역 캡처')
        self._btn_region.setToolTip('캔버스에서 드래그로 영역을 선택해 캡처합니다')
        self._btn_region.setStyleSheet(btn_style)
        self._btn_region.clicked.connect(self._on_region_capture)
        snap_btn_row.add_widget(self._btn_region)

        self._btn_view = QPushButton('보기')
        self._btn_view.setToolTip('선택한 스냅샷을 새 창에서 크게 확인합니다')
        self._btn_view.setStyleSheet(btn_style)
        self._btn_view.clicked.connect(self._on_view_snapshot)
        snap_btn_row.add_widget(self._btn_view)

        self._btn_save = QPushButton('💾 저장')
        self._btn_save.setToolTip('선택한 스냅샷을 PNG/JPG 파일로 저장합니다')
        self._btn_save.setStyleSheet(btn_style)
        self._btn_save.clicked.connect(self._on_save_snapshot)
        snap_btn_row.add_widget(self._btn_save)

        self._btn_insert = QPushButton('📄 PDF삽입')
        self._btn_insert.setToolTip('선택한 스냅샷을 현재 PDF 페이지에 이미지로 삽입합니다')
        self._btn_insert.setStyleSheet(btn_style)
        self._btn_insert.clicked.connect(self._on_insert_pdf)
        snap_btn_row.add_widget(self._btn_insert)

        self._btn_compare = QPushButton('🔍 비교')
        self._btn_compare.setToolTip('두 스냅샷을 나란히 비교합니다')
        self._btn_compare.setStyleSheet(btn_style)
        self._btn_compare.clicked.connect(self._on_compare)
        snap_btn_row.add_widget(self._btn_compare)

        root.addWidget(snap_btn_row)

        # ── 클리어 버튼 행 ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_snap = QPushButton('스냅샷 비우기')
        clear_snap.setStyleSheet(btn_style)
        clear_snap.clicked.connect(self.clear_snapshots)
        clear_clip = QPushButton('클립보드 비우기')
        clear_clip.setStyleSheet(btn_style)
        clear_clip.clicked.connect(self.clear_clipboard_history)
        btn_row.addWidget(clear_snap)
        btn_row.addWidget(clear_clip)
        root.addLayout(btn_row)

    def _make_list(self) -> QListWidget:
        lw = QListWidget(self)
        lw.setIconSize(QSize(96, 96))
        lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lw.itemDoubleClicked.connect(self._restore_item)
        return lw

    # ── 공개 API ────────────────────────────────────────────────────

    def show_snapshots(self):
        self._tabs.setCurrentWidget(self._snapshot_list)

    def show_clipboard(self):
        self._tabs.setCurrentWidget(self._clipboard_list)

    def add_snapshot(self, pixmap: QPixmap):
        if pixmap.isNull():
            return
        self._snapshot_items.insert(0, {
            'kind':   'image',
            'pixmap': QPixmap(pixmap),
            'label':  f'{pixmap.width()}x{pixmap.height()} 스냅샷',
        })
        self._snapshot_items = self._snapshot_items[:self._max_items]
        self._reload_snapshots()

    def add_clipboard_text(self, text: str):
        text = (text or '').strip()
        if not text:
            return
        if self._clipboard_items and self._clipboard_items[0].get('text') == text:
            return
        self._clipboard_items.insert(0, {
            'kind':  'text',
            'text':  text,
            'label': self._trim(text),
        })
        self._clipboard_items = self._clipboard_items[:self._max_items]
        self._reload_clipboard()

    def add_clipboard_image(self, pixmap: QPixmap):
        if pixmap.isNull():
            return
        self._clipboard_items.insert(0, {
            'kind':   'image',
            'pixmap': QPixmap(pixmap),
            'label':  f'{pixmap.width()}x{pixmap.height()} 이미지',
        })
        self._clipboard_items = self._clipboard_items[:self._max_items]
        self._reload_clipboard()

    def clear_snapshots(self):
        self._snapshot_items.clear()
        self._reload_snapshots()

    def clear_clipboard_history(self):
        self._clipboard_items.clear()
        self._reload_clipboard()

    def snapshot_items(self) -> list[dict]:
        """현재 스냅샷 목록 반환 (비교 다이얼로그용)."""
        return list(self._snapshot_items)

    # ── 내부 ────────────────────────────────────────────────────────

    def _trim(self, text: str, limit: int = 80) -> str:
        text = ' '.join(text.split())
        return text if len(text) <= limit else text[:limit - 1] + '...'

    def _reload_snapshots(self):
        self._snapshot_list.clear()
        for entry in self._snapshot_items:
            self._snapshot_list.addItem(self._make_item(entry))

    def _reload_clipboard(self):
        self._clipboard_list.clear()
        for entry in self._clipboard_items:
            self._clipboard_list.addItem(self._make_item(entry))

    def _make_item(self, entry: dict) -> QListWidgetItem:
        item = QListWidgetItem(entry['label'])
        item.setData(Qt.ItemDataRole.UserRole, entry)
        if entry['kind'] == 'image':
            thumb = entry['pixmap'].scaled(
                96, 96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item.setIcon(QIcon(thumb))
        return item

    def _restore_item(self, item: QListWidgetItem):
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        if entry.get('kind') == 'text':
            self.restore_text_requested.emit(entry.get('text', ''))
        elif entry.get('kind') == 'image':
            self.restore_image_requested.emit(entry.get('pixmap', QPixmap()))

    # ── 버튼 핸들러 ────────────────────────────────────────────────

    def _preview_item(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole) or {}
        self._show_preview(entry.get('pixmap'))

    def _on_view_snapshot(self):
        px = self._selected_snapshot_pixmap()
        if px is None:
            QMessageBox.information(self, '스냅샷 보기', '확인할 스냅샷이 없습니다. 먼저 영역을 캡처해 주세요.')
            return
        self._show_preview(px)
        self._preview.activateWindow()

    def _show_preview(self, px):
        if px is None or px.isNull():
            return
        if self._preview is None:
            self._preview = SnapshotPreviewDialog(self)
        self._preview.set_snapshot(px)
        self._preview.show()
        self._preview.raise_()

    def _on_region_capture(self):
        """영역 캡처 모드 시작 요청."""
        self.region_capture_requested.emit()

    def _on_save_snapshot(self):
        """선택한 스냅샷을 파일로 저장."""
        px = self._selected_snapshot_pixmap()
        if px is None:
            QMessageBox.information(self, '저장', '저장할 스냅샷을 선택해 주세요.')
            return
        self.save_snapshot_requested.emit(px)

    def _on_insert_pdf(self):
        """선택한 스냅샷을 PDF 페이지에 삽입 요청."""
        px = self._selected_snapshot_pixmap()
        if px is None:
            QMessageBox.information(self, 'PDF 삽입', '삽입할 스냅샷을 선택해 주세요.')
            return
        self.insert_pdf_requested.emit(px)

    def _on_compare(self):
        """스냅샷 비교 다이얼로그 열기."""
        if not self._snapshot_items:
            QMessageBox.information(self, '비교', '비교할 스냅샷이 없습니다.')
            return
        self.compare_requested.emit(list(self._snapshot_items))

    def _selected_snapshot_pixmap(self) -> QPixmap | None:
        """현재 스냅샷 탭에서 선택된 항목의 QPixmap 반환. 없으면 None."""
        items = self._snapshot_list.selectedItems()
        if not items:
            # 아무것도 선택 안 됐으면 첫 번째 항목 사용
            if self._snapshot_items:
                return self._snapshot_items[0]['pixmap']
            return None
        entry = items[0].data(Qt.ItemDataRole.UserRole) or {}
        return entry.get('pixmap')
