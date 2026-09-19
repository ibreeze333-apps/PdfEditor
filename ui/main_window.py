# ui/main_window.py — MainWindow
from __future__ import annotations
import sys
import os
from pathlib import Path

from PySide6.QtGui import (
    QAction, QActionGroup, QKeySequence, QShortcut, QIcon, QClipboard, QColor,
    QPainter, QPen, QLinearGradient, QRadialGradient, QPainterPath, QPixmap
)
from PySide6.QtCore import (
    Qt, QSize, QTimer, QPointF, QRectF, QRect, QEvent, QObject,
)
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QFileDialog, QMessageBox,
    QStatusBar, QToolBar, QLabel, QComboBox, QSlider,
    QWidget, QHBoxLayout, QDockWidget, QApplication, QPushButton, QSizePolicy,
    QWidgetAction, QStyle, QSpinBox, QStackedWidget, QGraphicsDropShadowEffect,
    QTabWidget, QTabBar,
)
import config as _cfg



from ui.glass_button import GlassButton
from ui.liquid_glass import LiquidGlassMenuBar
from ui.flow_bar import FlowBar
from core.document  import PdfDocument
from core.renderer  import PageRenderer
from core.exporter  import Exporter
from ui.canvas_view import PdfCanvasView
from ui.thumbnail_panel import ThumbnailPanel
from ui.toolbar     import AnnotToolBar
from ui.clipboard_panel import ClipboardPanel
from ui.note_panel import NotePanel
from ui.text_draft_editor import TextDraftEditor
from ui.reflow_read_view import ReflowReadView
from ui.texts import UI
from utils.settings import AppSettings
from utils.annot_style import apply_settings_defaults
from ui.mainwin import (
    TabsMixin,
    PanelsMixin,
    FindNavMixin,
    ViewModesMixin,
    TextDraftMixin,
    FileOpsMixin,
    PageOpsMixin,
    EditOpsMixin,
    SnapshotMixin,
    AnnotMenuMixin,
    AutosaveMixin,
    SecurityMixin,
)
from ui.mainwin.autosave import _AUTOSAVE_DIR
from ui.mainwin.tabs import _DocTab
from ui.mainwin.toolbar_autohide import ToolbarAutoHideMixin
from utils.errlog import swallowed


class _WinButtonSync(QObject):
    """플로팅 창의 표시/숨김/닫힘을 툴바 버튼 체크 상태에 반영하는 필터."""

    def __init__(self, btn, win):
        super().__init__(win)
        self._btn = btn
        self._win = win
        win.installEventFilter(self)
        btn.setChecked(win.isVisible())

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close):
            # Close 는 처리 후에 visible 이 바뀌므로 다음 틱에 반영
            QTimer.singleShot(0, self._sync)
        return False

    def _sync(self):
        try:
            self._btn.setChecked(self._win.isVisible())
        except RuntimeError:
            pass   # 창/버튼이 이미 파괴됨


class MainWindow(
    TabsMixin,
    PanelsMixin,
    FindNavMixin,
    ViewModesMixin,
    TextDraftMixin,
    FileOpsMixin,
    PageOpsMixin,
    EditOpsMixin,
    SnapshotMixin,
    AnnotMenuMixin,
    AutosaveMixin,
    SecurityMixin,
    ToolbarAutoHideMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self._settings   = AppSettings.load()
        apply_settings_defaults(self._settings.tool_defaults)
        self._apply_dict_settings()
        self._dict_window = None   # 사전 창 (싱글톤)
        self._exporter = Exporter()

        # ── 탭 목록 ───────────────────────────────────────────────
        self._tabs: list[_DocTab] = []
        self._current_tab_idx: int = 0

        # ── 첫 번째 탭 생성 ──────────────────────────────────────
        first_tab = self._make_tab()
        self._tabs.append(first_tab)

        # ── 현재 탭 alias (코드 전체에서 self._doc 등으로 접근) ──
        self._doc      = first_tab.doc
        self._renderer = first_tab.renderer
        self._canvas   = first_tab.canvas
        self._thumbs   = first_tab.thumbs
        self._splitter = first_tab.splitter

        # ── 어노테이션 툴바 ──────────────────────────────────────
        self._annot_bar = AnnotToolBar(self._canvas)
        self._annot_bar.note_panel_requested.connect(self._show_note_panel)
        self._annot_bar.dict_requested.connect(lambda: self._open_dict_window())
        self._clipboard_guard = False
        self._book_view_active = False
        self._view_mode = UI.VIEW_SCROLL
        self._book_view_prev: dict | None = None
        self._text_draft_active = False
        self._reflow_active = False
        self._in_tab_close = False
        self._app_close_requested = False
        self._search_cursor: int = -1

        # ── 탭 위젯 ───────────────────────────────────────────────
        self._tab_widget = QTabWidget()
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(False)   # 커스텀 close 버튼 사용
        self._tab_widget.setMovable(True)
        # currentChanged는 addTab 이후에 연결 — 초기화 중 _on_tab_changed 호출 방지
        self._tab_widget.addTab(first_tab.splitter, '새 문서')
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._attach_tab_close_btn(0)
        # 탭바 표시 여부는 설정에 따름
        _tabs_visible = getattr(self._settings, 'tabs_enabled', True)
        self._tab_widget.tabBar().setVisible(_tabs_visible)
        # 새 탭 버튼 (탭바 오른쪽 코너)
        self._new_tab_btn = QPushButton('+')
        self._new_tab_btn.setToolTip('새 탭 열기 (Ctrl+T)')
        self._new_tab_btn.setFixedSize(28, 24)
        self._new_tab_btn.setStyleSheet(
            'QPushButton { font-size: 16px; font-weight: 700; border: none; '
            '  background: transparent; color: #6b7280; padding: 0; }'
            'QPushButton:hover { color: #4361ee; background: #eef2ff; border-radius: 5px; }')
        self._new_tab_btn.clicked.connect(lambda: self._new_tab())
        self._new_tab_btn.setVisible(_tabs_visible)
        self._tab_widget.setCornerWidget(self._new_tab_btn, Qt.Corner.TopRightCorner)

        # TextDraftEditor/ReflowReadView는 QFontComboBox 채우기 비용
        # (합쳐서 ~1.7초) 때문에 첫 사용 시점에 지연 생성한다
        # (_text_draft/_reflow_view 프로퍼티 참고)
        self._text_draft_widget: TextDraftEditor | None = None
        self._reflow_view_widget: ReflowReadView | None = None
        self._simple_text_editor = None
        self._central_stack = QStackedWidget(self)
        self._central_stack.addWidget(self._tab_widget)   # index 0
        self.setCentralWidget(self._central_stack)
        self.setMenuBar(LiquidGlassMenuBar(self))
        self._menubar = self.menuBar()
        self._menubar.setNativeMenuBar(False)
        self._menubar.setVisible(True)
        self._init_toolbar_autohide()

        # ── 툴바 ──────────────────────────────────────────────────
        # 행1: 어노테이션 도구들 + 저장·OCR(맨 뒤) / 행2: 문서 조작 버튼들
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._annot_bar)
        self._annot_bar.setVisible(True)
        self._build_view_toolbar()   # 저장·OCR → 행1 맨 뒤
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self._build_doc_toolbar()    # 행2

        # OCR 패널 / PDF 번역 패널 (지연 생성 도킹)
        # 텍스트 번역 창 (사전 창과 동일한 싱글톤 플로팅 창)
        self._ocr_panel         = None
        self._ocr_restore_geometry = None
        self._ocr_restore_splitter = None
        self._ocr_restore_splitter_sizes = None
        self._ocr_restore_maximized = False
        self._ollama_window     = None


        self._clipboard_panel = ClipboardPanel(self)
        self._clipboard_panel.restore_text_requested.connect(self._restore_clipboard_text)
        self._clipboard_panel.restore_image_requested.connect(self._restore_clipboard_image)
        self._clipboard_panel.save_snapshot_requested.connect(self._save_snapshot_to_file)
        self._clipboard_panel.insert_pdf_requested.connect(self._insert_snapshot_to_pdf)
        self._clipboard_panel.region_capture_requested.connect(self._start_region_capture)
        self._clipboard_panel.compare_requested.connect(self._open_snapshot_compare)
        # 임시 파일 추적 (프로그램 종료 시 정리)
        self._snapshot_tmp_files: list[str] = []
        self._clip_dock = QDockWidget('스냅샷 / 클립보드', self)
        self._clip_dock.setObjectName('clipboard_snapshot_dock')
        self._clip_dock.setWidget(self._clipboard_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._clip_dock)
        self._clip_dock.visibilityChanged.connect(
            lambda visible: (
                self._clip_corner_btn.setChecked(visible)
                if hasattr(self, '_clip_corner_btn') else None
            ))
        self._clip_dock.hide()   # 시작 시 숨김

        self._note_panel = NotePanel(self)
        self._note_panel.note_activated.connect(self._open_note_entry)
        self._note_panel.refresh_requested.connect(self._refresh_note_panel)
        self._note_dock = QDockWidget('메모 목록', self)
        self._note_dock.setObjectName('note_list_dock')
        self._note_dock.setWidget(self._note_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._note_dock)
        self._note_dock.hide()
        # 메모목록 버튼(툴바에서 먼저 생성됨)의 체크 상태를 dock 표시와 동기화
        if hasattr(self, '_notes_btn'):
            self._note_dock.visibilityChanged.connect(self._notes_btn.setChecked)
        self._install_large_dock_titlebars()

        # ── 찾기 (찾기 메뉴) ──────────────────────────────────────
        # 문서 오른쪽 위의 찾기 막대 + 오른쪽 '검색' 결과 패널 (ui/mainwin/find_nav.py)
        self._init_find()

        # ── 상태 바 ───────────────────────────────────────────────
        self._status_lbl   = QLabel('파일을 열거나 새로 만드세요.')
        self._page_lbl     = QLabel('')
        self._page_lbl.setStyleSheet('color: #6b7280; padding: 0 6px;')
        self._pending_lbl  = QLabel('')
        self._pending_lbl.setStyleSheet('color: #4361ee; font-weight: bold; padding: 0 6px;')
        sb = self.statusBar()
        sb.addWidget(self._status_lbl, 1)
        # permanent 위젯: 보류 → 페이지 → (네비게이션은 _build_doc_toolbar에서 추가됨)
        sb.addPermanentWidget(self._pending_lbl)
        sb.addPermanentWidget(self._page_lbl)

        # ── 메뉴 ──────────────────────────────────────────────────
        self._build_menu()

        # ── 시그널 ────────────────────────────────────────────────
        self._connect_tab_signals(first_tab)
        # (_text_draft/_reflow_view의 시그널 연결은 지연 생성 시점에 수행)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        # ── 창 설정 ───────────────────────────────────────────────
        self.setWindowTitle(_cfg.window_title())
        _base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _ico  = os.path.join(_base, 'logo.ico')
        if not os.path.exists(_ico):
            _ico = os.path.join(_base, 'logo.png')
        self.setWindowIcon(QIcon(_ico))
        self.resize(self._settings.window_w, self._settings.window_h)
        self.setAcceptDrops(True)   # 파일 드래그·드롭 활성화

        # ── 자동 저장 타이머 (5분) ────────────────────────────────
        os.makedirs(_AUTOSAVE_DIR, exist_ok=True)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._autosave_timer.start(30 * 1000)   # 30초
        # 시작 1초 후 복구 파일 확인 (이벤트 루프 진입 후 실행)
        QTimer.singleShot(1000, self._check_recovery)

        # ── 전체 UI 스타일 ──────────────────────────────────────
        self.setStyleSheet("""
            QMainWindow { background: #f0f2f5; }

            QMenuBar {
                background: #e9edf2;
                color: #263546;
                padding: 4px 8px;
                min-height: 0px;
                border-bottom: 1px solid #ced7e1;
                font-size: 14px;
                spacing: 4px;
            }
            QMenuBar::item {
                padding: 12px 20px;
                background: transparent;
                color: transparent;
                margin: 0;
                border: none;
            }
            QMenuBar::item:selected, QMenuBar::item:pressed {
                background: transparent;
                color: transparent;
            }

            QMenu {
                background: #ffffff;
                border: 1.5px solid #d0d8f5;
                border-radius: 9px;
                color: #1e2532;
                padding: 6px 0;
            }
            QMenu::item {
                padding: 7px 24px 7px 16px;
                border-radius: 5px;
                margin: 1px 5px;
                font-size: 14px;
                color: #2e3555;
            }
            QMenu::item:selected {
                background: #eef2ff;
                color: #4361ee;
            }
            QMenu::item:disabled { color: #b0b8cc; }
            QMenu::separator {
                height: 1px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 transparent, stop:0.15 #d0d8f5,
                    stop:0.85 #d0d8f5, stop:1 transparent);
                margin: 5px 10px;
            }
            QMenu::indicator { width: 14px; height: 14px; margin-left: 6px; }

            QToolBar {
                background: #e9edf2;
                border-bottom: 1px solid #e0e3e8;
                spacing: 4px;
                padding: 1px 10px;
            }
            QToolBar::separator { width: 1px; background: #d1d5e0; margin: 4px 6px; }
            QToolBar QToolButton {
                padding: 5px 11px;
                min-width: 52px;
                min-height: 30px;
                border-radius: 6px;
                border: 1.5px solid #d1d5e0;
                color: #3a3f52;
                background: #ffffff;
                font-size: 12px;
            }
            QToolBar QToolButton:hover {
                background: #eef2ff;
                color: #4361ee;
                border-color: #4361ee;
            }
            QToolBar QToolButton:checked {
                background: #4361ee;
                color: #ffffff;
                border-color: #4361ee;
                font-weight: bold;
            }
            QToolBar QToolButton:pressed {
                background: #3451d1;
                color: #ffffff;
                border-color: #2c44b8;
            }

            QComboBox {
                padding: 4px 10px;
                min-height: 30px;
                border: 1.5px solid #d1d5e0;
                border-radius: 6px;
                background: #ffffff;
                color: #1e2532;
            }
            QComboBox:hover { border-color: #4361ee; }
            QComboBox::drop-down { border: none; width: 22px; }

            QPushButton {
                padding: 5px 14px;
                min-height: 30px;
                border-radius: 6px;
                border: 1.5px solid #d1d5e0;
                background: #ffffff;
                color: #1e2532;
                font-weight: 500;
            }
            QPushButton:hover { background: #f0f2f5; border-color: #b0b8cc; }
            QPushButton:pressed { background: #e8ecf5; }
            QPushButton:disabled { color: #b0b8cc; border-color: #e8eaef; background: #f8f9fc; }

            QSpinBox {
                min-height: 30px;
                border: 1.5px solid #d1d5e0;
                border-radius: 6px;
                padding: 2px 6px;
                background: #ffffff;
                color: #1e2532;
            }
            QSpinBox:hover { border-color: #4361ee; }

            QDockWidget::title {
                background: #f0f2f5;
                padding: 9px 14px;
                border-bottom: 1px solid #e0e3e8;
                font-weight: bold;
                color: #1e2532;
            }
            QDockWidget::close-button, QDockWidget::float-button { width: 30px; height: 30px; border-radius: 4px; }
            QDockWidget::close-button:hover, QDockWidget::float-button:hover { background: #e0e3e8; }

            QStatusBar {
                background: #ffffff;
                border-top: 1px solid #e0e3e8;
                color: #6b7280;
                padding: 2px 8px;
            }

            QProgressBar { min-height: 18px; border-radius: 4px; border: 1px solid #d1d5e0; background: #f0f2f5; }
            QProgressBar::chunk { background: #4361ee; border-radius: 4px; }

            QTabWidget::pane { border: none; }
            QTabWidget::tab-bar { alignment: left; }
            QTabBar { background: #f0f2f5; }
            QTabBar::tab {
                background: #e8ecf5;
                color: #6b7280;
                padding: 5px 14px;
                min-width: 100px;
                max-width: 200px;
                border: 1px solid #d1d5e0;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1e2532;
                font-weight: 600;
                border-bottom: 2px solid #ffffff;
            }
            QTabBar::tab:hover:!selected { background: #dde4f5; color: #4361ee; }
            QTabBar::close-button {
                subcontrol-position: right;
                width: 16px;
                height: 16px;
                border-radius: 3px;
                margin: 0 2px;
            }
            QTabBar::close-button:hover {
                background: #fca5a5;
            }
        """)
        self._apply_menu_button_style(self._settings.menu_button_style, persist=False)



    def _apply_menu_button_style(self, style, persist=True):
        from ui.menu_theme import CLASSIC_MENU, LIQUID_MENU, CLASSIC_BUTTONS
        style = 'classic' if style == 'classic' else 'liquid'
        self._settings.menu_button_style = style
        self._menubar.setProperty('menuButtonStyle', style)
        self._menubar.setStyleSheet(CLASSIC_MENU if style == 'classic' else LIQUID_MENU)
        for name, sheet in CLASSIC_BUTTONS.items():
            getattr(self, name)._classic_style_sheet = sheet
        for button in self.findChildren(GlassButton):
            button.set_button_style(style)
        for button in (self._page_prev_btn, self._page_next_btn):
            button.setMinimumWidth(36 if style == 'classic' else 48)
            button.setFixedWidth(36 if style == 'classic' else 48)
        self._page_go_btn.setMinimumWidth(58 if style == 'classic' else 68)
        self._page_go_btn.setMaximumWidth(16777215)
        current = self.styleSheet()
        old = 'QToolBar {\n                background: '
        for colour in ('#e9edf2', '#f8f9fc'):
            current = current.replace(old + colour + ';',
                old + ('#f8f9fc' if style == 'classic' else '#e9edf2') + ';')
        self.setStyleSheet(current)
        for key, action in self._menu_style_actions.items():
            action.setChecked(key == style)
        for flow in self.findChildren(FlowBar):
            flow._base_widths.clear()
            QTimer.singleShot(0, flow._fit)
        self._menubar.updateGeometry()
        self._menubar.update()
        if persist and not self._settings.save():
            QMessageBox.warning(self, '설정 저장', '스타일은 적용됐지만 설정을 저장하지 못했습니다. 다음 실행에는 이전 설정이 사용됩니다.')

    def _toggle_text_edit_mode(self):
        """본문 편집 모드 토글 — 켜면 문단 클릭으로 여러 줄 편집."""
        on = self._text_edit_btn.isChecked()
        self._canvas.set_text_edit_mode(on)
        if on:
            self._status_lbl.setText('본문 편집 모드: 문단을 클릭해 편집하세요 (Ctrl+Enter 확정, Esc 취소)')
        else:
            self._status_lbl.setText('본문 편집 모드 꺼짐')

    def _open_log_folder(self):
        """오류/멈춤(freeze) 로그가 저장되는 폴더를 탐색기로 연다."""
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        os.startfile(log_dir)

    # ── 창 토글 버튼 (열림 상태를 버튼 체크로 표시) ─────────────────

    def _sync_window_button(self, btn, win):
        """싱글톤 창에 표시 상태 동기화 필터를 1회 설치."""
        if win is None:
            btn.setChecked(False)
            return
        if getattr(win, '_btn_sync_obj', None) is None:
            win._btn_sync_obj = _WinButtonSync(btn, win)
        else:
            btn.setChecked(win.isVisible())

    def _toggle_dict_window_btn(self):
        win = self._dict_window
        if win is not None and win.isVisible():
            win.hide()
        else:
            self._open_dict_window()
            self._sync_window_button(self._dict_btn, self._dict_window)

    def _toggle_ollama_window_btn(self):
        win = self._ollama_window
        if win is not None and win.isVisible():
            win.hide()
        else:
            self._open_ollama_window()
            self._sync_window_button(self._ollama_btn, self._ollama_window)

    def _toggle_translate_hub_btn(self):
        win = getattr(self, '_translate_hub_win', None)
        if win is not None and win.isVisible():
            win.hide()
        else:
            self._open_translate_hub()
            self._sync_window_button(
                self._translate_btn, self._translate_hub_win)

    # ── 텍스트 초안 에디터 (지연 생성) ──────────────────────────────

    @property
    def _text_draft(self) -> TextDraftEditor:
        """텍스트 초안 에디터를 첫 접근 시점에 생성한다.

        QFontComboBox 글꼴 목록 채우기가 ~1.3초 걸려 시작 시간을
        지배하므로, 초안 모드에 실제로 진입할 때까지 미룬다.
        """
        if self._text_draft_widget is None:
            self._text_draft_widget = TextDraftEditor(self)
            self._central_stack.addWidget(self._text_draft_widget)
            self._text_draft_widget.close_requested.connect(
                self._exit_text_draft_mode_requested)
        return self._text_draft_widget

    @property
    def _reflow_view(self) -> ReflowReadView:
        """읽기(reflow) 뷰를 첫 접근 시점에 생성한다 (_text_draft와 동일 이유)."""
        if self._reflow_view_widget is None:
            self._reflow_view_widget = ReflowReadView(self)
            self._central_stack.addWidget(self._reflow_view_widget)
            self._reflow_view_widget.page_changed.connect(self._on_page_changed)
        return self._reflow_view_widget

    # ── 뷰 툴바 ────────────────────────────────────────────────────


    def _build_view_toolbar(self):
        """저장·본문인식 버튼 — 행1 어노테이션 툴바 맨 뒤에 이어 붙인다.

        예전에는 별도 QToolBar 로 같은 행을 나눠 썼는데, 화면 배율이 높아
        폭이 모자라면 Qt 가 이 툴바를 잘라내 두 버튼이 통째로 사라졌다.
        같은 줄바꿈 컨테이너에 넣으면 자리가 없을 때 다음 줄로 내려간다.
        """
        self._save_corner_btn = GlassButton('PDF 저장')
        self._save_corner_btn.set_accent('#6fa8dc')
        self._save_corner_btn.setToolTip('현재 문서를 PDF로 저장 (Ctrl+S)')
        self._save_corner_btn.setMinimumWidth(76)
        self._save_corner_btn.clicked.connect(self._save)

        self._ocr_corner_btn = GlassButton(UI.BTN_OCR)
        self._ocr_corner_btn.set_accent('#9aa3b2')
        self._ocr_corner_btn.setToolTip(UI.TIP_OCR)
        self._ocr_corner_btn.setCheckable(True)
        self._ocr_corner_btn.setMinimumWidth(60)
        self._ocr_corner_btn.clicked.connect(self._toggle_ocr_btn)

        self._annot_bar.add_trailing_widget(self._save_corner_btn, separator=True)
        self._annot_bar.add_trailing_widget(self._ocr_corner_btn)

        # 예전 코드가 참조하는 이름 — 이제 행1 툴바 자체를 가리킨다
        self._view_toolbar = self._annot_bar
        self._glass_buttons = [self._save_corner_btn, self._ocr_corner_btn]
        QTimer.singleShot(0, self._refresh_glass_backdrop_cache)



    def _refresh_glass_backdrop_cache(self):
        if not hasattr(self, '_glass_buttons') or not hasattr(self, '_view_toolbar'):
            return
        toolbar = self._view_toolbar
        try:
            toolbar_rect = toolbar.rect()
            if toolbar_rect.isEmpty():
                return
            shot = toolbar.grab(toolbar_rect)
            if shot.isNull():
                return
            img = shot.toImage()
            sw = max(16, img.width() // 5)
            sh = max(16, img.height() // 5)
            blur = img.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            blur = blur.scaled(img.width(), img.height(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            px = QPixmap.fromImage(blur)
            for btn in self._glass_buttons:
                if btn is None:
                    continue
                tl = btn.mapTo(toolbar, btn.rect().topLeft())
                src = QRect(tl.x(), tl.y(), btn.width(), btn.height())
                btn.set_frost_cache(px, src)
        except Exception:
            return
    def _toggle_ocr_btn(self):
        """OCR 도구 버튼과 관련 메뉴를 만든다."""
        self._toggle_ocr()

    # 문서 메뉴 구성 ── ───────────────────────────────────────────────

    def _build_menu(self):
        mb = self._menubar
        mb.clear()

        fm = mb.addMenu(UI.MENU_FILE)
        self._add_action(fm, UI.ACT_NEW, self._new, 'Ctrl+N')
        self._add_action(fm, UI.ACT_OPEN, self._open, 'Ctrl+O')
        self._add_action(fm, '새 탭에서 열기', self._open_in_new_tab)
        fm.addSeparator()
        self._add_action(fm, UI.ACT_SAVE, self._save, 'Ctrl+S')
        self._add_action(fm, UI.ACT_SAVE_AS, self._save_as, 'Ctrl+Shift+S')
        fm.addSeparator()

        conv = fm.addMenu(UI.MENU_EXPORT)
        self._add_action(conv, 'Markdown(.md)로 내보내기', self._export_md)
        self._add_action(conv, 'Markdown(.md)로 내보내기 (테이블 포함)', self._export_md_with_tables)
        self._add_action(conv, '이미지에서 PDF 만들기', self._img_to_pdf)
        self._add_action(conv, 'PNG/JPEG로 내보내기', self._export_image)
        self._add_action(conv, '플래튼하고 이미지 PDF로 내보내기', self._export_flattened_image_pdf)

        util = fm.addMenu(UI.MENU_PDF_UTIL)
        self._add_action(util, '큰 PDF 용량 줄이기', self._compress_pdf)
        self._add_action(util, '여러 이미지/PDF 한 번에 합치기', self._image_pdf_merge)
        self._add_action(util, '큰 문서를 PDF로 분할', self._split_by_size)

        fm.addSeparator()
        self._add_action(fm, '📂 로그 폴더 열기', self._open_log_folder)
        fm.addSeparator()
        self._add_action(fm, UI.ACT_EXIT, self._request_app_close, 'Ctrl+Q')

        em = mb.addMenu(UI.MENU_EDIT)
        self._add_action(em, UI.ACT_UNDO, self._undo, 'Ctrl+Z')
        em.addSeparator()
        self._add_action(em, UI.ACT_TEXT_EDITOR, self._open_text_editor, 'Ctrl+T')
        em.addSeparator()
        self._add_action(em, UI.ACT_DICT, lambda: self._open_dict_window(), 'Ctrl+D')
        self._add_action(em, UI.ACT_PREFS, self._open_preferences)

        # 찾기는 편집 메뉴에서 떼어 독립 메뉴로 둔다 (찾기/바꾸기도 함께 옮김)
        self._build_find_menu(mb)

        pm = mb.addMenu(UI.MENU_PAGE)
        self._add_action(pm, UI.ACT_INSERT_BLANK, self._insert_blank)
        self._add_action(pm, UI.ACT_INSERT_IMAGE_PAGE, self._insert_img_page)
        self._add_action(pm, UI.ACT_DELETE_PAGE, self._delete_page)
        self._add_action(pm, UI.ACT_CROP_PAGE, self._crop_page)
        pm.addSeparator()
        self._add_action(pm, UI.ACT_ROTATE_CW, self._rotate_cw)
        self._add_action(pm, UI.ACT_ROTATE_CCW, self._rotate_ccw)
        pm.addSeparator()
        self._add_action(pm, UI.ACT_SPLIT_PDF, self._split_pdf)
        self._add_action(pm, UI.ACT_MERGE_PDF, self._merge_pdf)

        cm = mb.addMenu(UI.MENU_COMPOSE)
        self._add_action(cm, UI.ACT_WATERMARK, self._add_watermark)
        self._add_action(cm, UI.ACT_HEADER_FOOTER, self._header_footer)

        # ── 보안 메뉴 ────────────────────────────────────────────
        sm = mb.addMenu('보안(&S)')
        self._add_action(sm, '🔒 문서 암호 / 권한 설정…', self._open_encrypt_dialog)
        self._add_action(sm, '💧 워터마크 삽입…', self._add_watermark)
        self._add_action(sm, '🖊 개인정보 교정(가림)…', self._open_redact_dialog)
        sm.addSeparator()
        self._add_action(sm, '✒ 디지털 서명 (인증서·표준)…', self._open_cert_sign_dialog)
        # QAction.triggered 는 checked(bool) 를 넘기므로 auto 인자를 가린다 — 명시 호출
        self._add_action(sm, '🔎 서명 확인…', lambda: self._verify_signatures(auto=False))
        self._add_action(sm, '📤 공개 인증서 내보내기 (.p7b/.cer)…',
                         self._export_public_cert)
        self._add_action(sm, '✍ 서명 도장 (이미지·눈으로만)…', self._open_signature_dialog)

        vm = mb.addMenu(UI.MENU_VIEW)
        style_menu = vm.addMenu('메뉴 버튼 스타일')
        self._menu_style_group = QActionGroup(self)
        self._menu_style_group.setExclusive(True)
        self._menu_style_actions = {}
        for key, label in (('liquid', 'Liquid Glass'), ('classic', '기존 스타일')):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self._settings.menu_button_style == key)
            action.triggered.connect(lambda checked=False, value=key: self._apply_menu_button_style(value))
            self._menu_style_group.addAction(action)
            style_menu.addAction(action)
            self._menu_style_actions[key] = action
        vm.addSeparator()
        self._thumbnail_toggle_action = QAction('페이지 썸네일 표시', self)
        self._thumbnail_toggle_action.setCheckable(True)
        self._thumbnail_toggle_action.setChecked(False)
        self._thumbnail_toggle_action.triggered.connect(self._toggle_thumbnail_panel)
        vm.addAction(self._thumbnail_toggle_action)
        self._add_action(vm, UI.ACT_OCR_PANEL, self._toggle_ocr, 'Ctrl+Shift+O')
        self._add_action(vm, 'Ollama 분석', self._open_ollama_window, 'Ctrl+Alt+A')
        self._add_action(vm, UI.ACT_SNAPSHOT_PANEL, self._toggle_snapshot_panel, 'Ctrl+Shift+C')
        self._add_action(vm, UI.ACT_NOTE_PANEL, self._show_note_panel, 'Ctrl+Shift+M')
        self._add_action(vm, UI.ACT_BOOK_VIEW, self._toggle_book_view, 'Ctrl+Shift+B')
        # 상단 툴바 자동 숨김 토글 (문서 넓게 보기). 메뉴바에 두어 툴바가 숨어도
        # 언제든 여기서 끌 수 있게 한다.
        self._toolbar_autohide_action = QAction('상단 툴바 자동 숨김', self)
        self._toolbar_autohide_action.setCheckable(True)
        self._toolbar_autohide_action.setChecked(False)
        self._toolbar_autohide_action.setShortcut('F11')
        self._toolbar_autohide_action.triggered.connect(self.set_toolbar_autohide)
        vm.addAction(self._toolbar_autohide_action)
        vm.addSeparator()
        # 탭 메뉴
        self._add_action(vm, '새 탭 열기', self._new_tab, 'Ctrl+Shift+T')
        self._close_tab_action = self._add_action(vm, '현재 탭 닫기', lambda: self._close_tab(self._tab_widget.currentIndex()), 'Ctrl+W')
        self._close_tab_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._tab_toggle_action = QAction('탭 바 표시', self)
        self._tab_toggle_action.setCheckable(True)
        self._tab_toggle_action.setChecked(getattr(self._settings, 'tabs_enabled', True))
        self._tab_toggle_action.triggered.connect(self._toggle_tab_bar)
        vm.addAction(self._tab_toggle_action)
        vm.addSeparator()
        self._add_action(vm, UI.ACT_FIT_PAGE, lambda: self._canvas.fit_page(), 'Ctrl+0')
        self._add_action(vm, UI.ACT_FIT_WIDTH, self._fit_width, 'Ctrl+Shift+W')
        self._add_action(vm, UI.ACT_ACTUAL_SIZE, self._actual_size, 'Ctrl+1')

        # ── 번역 메뉴 ────────────────────────────────────────────
        trans_m = mb.addMenu('번역')
        self._add_action(trans_m, '번역 허브 열기', self._open_translate_hub, 'Ctrl+Shift+H')
        trans_m.addSeparator()
        self._add_action(trans_m, 'AI 제공자 설정 (API 키)', self._open_ai_provider_settings)

        calc_m = mb.addMenu(UI.MENU_CALC)
        self._add_action(calc_m, UI.ACT_CALC_NORMAL, lambda: self._open_calculator(0))
        self._add_action(calc_m, UI.ACT_CALC_ENGINEERING, lambda: self._open_calculator(1))
        self._add_action(calc_m, UI.ACT_CALC_UNIT, lambda: self._open_calculator(2))
        self._add_action(calc_m, UI.ACT_CALC_DATE, lambda: self._open_calculator(3))
        calc_m.addSeparator()
        lm = calc_m.addMenu(UI.MENU_LAW_CALC)
        self._add_action(lm, UI.ACT_CALC_DELAY, lambda: self._open_calculator(4, 0))
        self._add_action(lm, UI.ACT_CALC_STAMP, lambda: self._open_calculator(4, 1))
        self._add_action(lm, UI.ACT_CALC_RATIO, lambda: self._open_calculator(4, 2))
        self._add_action(lm, UI.ACT_CALC_AGE, lambda: self._open_calculator(4, 3))
        self._add_action(lm, UI.ACT_CALC_RETIRE, lambda: self._open_calculator(4, 4))
        self._add_action(lm, UI.ACT_CALC_LAWSUIT, lambda: self._open_calculator(4, 5))
        self._add_action(lm, UI.ACT_CALC_INTEREST, lambda: self._open_calculator(4, 6))
        self._add_action(lm, UI.ACT_CALC_SALARY, lambda: self._open_calculator(4, 7))
        self._add_action(lm, UI.ACT_CALC_INHERIT, lambda: self._open_calculator(4, 8))
        calc_m.addSeparator()
        self._add_action(calc_m, UI.ACT_CALC_OPEN, lambda: self._open_calculator(0), 'Ctrl+Shift+K')

        print_m = mb.addMenu(UI.MENU_PRINT)
        self._add_action(print_m, UI.ACT_PRINT, self._print_windows, 'Ctrl+P')

    def _build_doc_toolbar(self):
        dbar = QToolBar(UI.DOC_TOOLBAR)
        dbar.setObjectName('doc_toolbar')
        dbar.setMovable(False)
        dbar.setFloatable(False)

        # 폭이 모자라면 다음 줄로 넘기는 컨테이너 (ui/flow_bar.py)
        dflow = FlowBar(dbar)
        _dflow_action = QWidgetAction(dbar)
        _dflow_action.setDefaultWidget(dflow)
        dbar.addAction(_dflow_action)
        self._doc_flow = dflow

        # ── 상태바에 페이지 네비게이션 위젯 구성 ──────────────────
        # ── 왼쪽: 변경사항 적용 / 취소 ─────────────────────────────
        self._apply_btn = GlassButton(UI.BTN_APPLY)
        self._apply_btn.setToolTip(UI.TIP_APPLY)
        self._apply_btn.setShortcut(QKeySequence('Ctrl+Shift+A'))
        self._apply_btn.set_accent('#39b79c')
        self._apply_btn.clicked.connect(self._apply_pending)
        self._apply_btn.setEnabled(False)
        dflow.add_widget(self._apply_btn)

        self._discard_btn = GlassButton(UI.BTN_DISCARD)
        self._discard_btn.setToolTip(UI.TIP_DISCARD)
        self._discard_btn.set_accent('#e7a0ab')
        self._discard_btn.clicked.connect(self._discard_pending)
        self._discard_btn.setEnabled(False)
        dflow.add_widget(self._discard_btn)

        # 현재 확대 크기 표시 (참고용, 스냅샷 창 버튼 앞)
        self._zoom_pct_lbl = QLabel('100%')
        self._zoom_pct_lbl.setToolTip('현재 확대 크기')
        self._zoom_pct_lbl.setStyleSheet(
            'QLabel { color: #4b5563; font-weight: 600; padding: 0 10px; }')
        self._zoom_pct_lbl.setMinimumWidth(56)
        self._zoom_pct_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dflow.add_widget(self._zoom_pct_lbl)

        self._clip_corner_btn = GlassButton('스냅샷 창')
        self._clip_corner_btn.set_accent('#7fbf95')
        self._clip_corner_btn.setToolTip('스냅샷/클립보드 창 열기·닫기 (Ctrl+Shift+C)')
        self._clip_corner_btn.setCheckable(True)
        self._clip_corner_btn.setMinimumWidth(88)
        self._clip_corner_btn.clicked.connect(self._toggle_snapshot_panel)
        dflow.add_widget(self._clip_corner_btn)

        self._snap_shoot_btn = GlassButton('📷 찍기')
        self._snap_shoot_btn.set_accent('#7fbf95')
        self._snap_shoot_btn.setToolTip(
            '현재 PDF 화면을 캡처하여 스냅샷 창에 저장합니다.\n'
            '스냅샷 창에서 항목을 더블클릭하면 클립보드로 복사됩니다.')
        self._snap_shoot_btn.setMinimumWidth(72)
        self._snap_shoot_btn.clicked.connect(self._do_snapshot)
        dflow.add_widget(self._snap_shoot_btn)

        self._snap_region_btn = GlassButton('✂ 영역')
        self._snap_region_btn.set_accent('#7fbf95')
        self._snap_region_btn.setToolTip('드래그로 원하는 영역만 선택해서 스냅샷으로 저장합니다.')
        self._snap_region_btn.setMinimumWidth(72)
        self._snap_region_btn.clicked.connect(self._start_region_capture)
        dflow.add_widget(self._snap_region_btn)
        dflow.add_separator()

        # 본문 글자 편집 모드 (문단 클릭 → 여러 줄 편집)
        self._text_edit_btn = GlassButton('✎ 본문편집')
        self._text_edit_btn.set_accent('#9b8ede')
        self._text_edit_btn.setToolTip(
            '본문 편집 모드: 켜고 문단을 클릭하면 여러 줄로 편집합니다.\n'
            '글꼴·크기·색은 자동 감지되고 정렬이 유지됩니다. (Ctrl+Enter 확정)')
        self._text_edit_btn.setMinimumWidth(84)
        self._text_edit_btn.setCheckable(True)
        self._text_edit_btn.clicked.connect(self._toggle_text_edit_mode)
        dflow.add_widget(self._text_edit_btn)
        dflow.add_separator()

        # ── 오른쪽: 메모목록 | 사전 | 책 보기 | 보기 선택 ───────────
        # 창을 여는 버튼들은 체크형으로 — 열려 있는 동안 반전 스타일로
        # 표시돼 어떤 창이 떠 있는지 한눈에 보인다. 다시 누르면 닫힘.
        self._notes_btn = GlassButton(UI.BTN_NOTE_LIST)
        self._notes_btn.set_accent('#e8c46a')
        self._notes_btn.setToolTip(UI.TIP_NOTE_LIST)
        self._notes_btn.setMinimumWidth(88)
        self._notes_btn.setCheckable(True)
        self._notes_btn.clicked.connect(self._show_note_panel)
        dflow.add_widget(self._notes_btn)

        self._dict_btn = GlassButton('📖 사전')
        self._dict_btn.set_accent('#79b6dd')
        self._dict_btn.setToolTip('사전 창 열기/닫기 (Ctrl+D)')
        self._dict_btn.setMinimumWidth(72)
        self._dict_btn.setCheckable(True)
        self._dict_btn.clicked.connect(self._toggle_dict_window_btn)
        dflow.add_widget(self._dict_btn)

        self._ollama_btn = GlassButton('🦙 Ollama')
        self._ollama_btn.set_accent('#a99ae0')
        self._ollama_btn.setToolTip('Ollama 분석 (요약·Q&A·용어추출·교정·어노테이션)')
        self._ollama_btn.setMinimumWidth(80)
        self._ollama_btn.setCheckable(True)
        self._ollama_btn.clicked.connect(self._toggle_ollama_window_btn)
        dflow.add_widget(self._ollama_btn)

        self._translate_btn = GlassButton('🌐 번역')
        self._translate_btn.set_accent('#7f93cf')
        self._translate_btn.setToolTip(
            '번역 허브 (Ctrl+Shift+H)\n'
            'Ollama 로컬 번역 · ChatGPT/Claude API · 웹 AI 번역')
        self._translate_btn.setMinimumWidth(72)
        self._translate_btn.setCheckable(True)
        self._translate_btn.clicked.connect(self._toggle_translate_hub_btn)
        dflow.add_widget(self._translate_btn)

        dflow.add_separator()

        # ── 오른쪽: 책 보기 + 보기 선택 ─────────────────────────
        self._book_btn = GlassButton(UI.BTN_BOOK_VIEW)
        self._book_btn.set_accent('#e5a76a')
        self._book_btn.setToolTip(UI.TIP_BOOK_VIEW)
        self._book_btn.setCheckable(True)
        self._book_btn.setMinimumWidth(82)
        self._book_btn.clicked.connect(self._toggle_book_view)
        dflow.add_widget(self._book_btn)

        dflow.add_widget(QLabel(UI.LABEL_VIEW))

        self._view_cb = QComboBox()
        # 전역 QSS 의 여백(4px 10px)은 툴바에서 과하다 — 폭을 아낀다
        self._view_cb.setStyleSheet('QComboBox { padding: 3px 6px; }')
        self._view_cb.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._view_cb.addItems([UI.VIEW_SINGLE, UI.VIEW_DOUBLE, UI.VIEW_BOOK, UI.VIEW_SCROLL])
        self._view_cb.currentTextChanged.connect(self._on_view_mode)
        # 선택 직후 캔버스로 포커스 복귀 — 콤보에 포커스가 남으면
        # 방향키가 페이지 넘김 대신 보기 모드를 바꿔 버린다
        self._view_cb.activated.connect(
            lambda *_: self._canvas.setFocus())
        self._view_cb.blockSignals(True)
        self._view_cb.setCurrentText(UI.VIEW_SCROLL)
        self._view_cb.blockSignals(False)
        dflow.add_widget(self._view_cb)

        dflow.add_separator()

        # ── 맨 뒤: 페이지 네비게이션 ─────────────────────────────
        self._page_prev_btn = GlassButton('‹')
        self._page_prev_btn.setToolTip(UI.TIP_PREV_PAGE)
        self._page_prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._page_prev_btn.setFixedWidth(48)
        self._page_prev_btn.set_accent('#94b7d3')
        self._page_prev_btn.clicked.connect(self._go_prev_page)
        dflow.add_widget(self._page_prev_btn)

        self._page_next_btn = GlassButton('›')
        self._page_next_btn.setToolTip(UI.TIP_NEXT_PAGE)
        self._page_next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._page_next_btn.setFixedWidth(48)
        self._page_next_btn.set_accent('#94b7d3')
        self._page_next_btn.clicked.connect(self._go_next_page)
        dflow.add_widget(self._page_next_btn)

        self._page_spin = QSpinBox()
        self._page_spin.setMinimum(1)
        self._page_spin.setMaximum(1)
        self._page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self._page_spin.setFixedWidth(84)
        dflow.add_widget(self._page_spin)

        self._page_go_btn = GlassButton('이동')
        self._page_go_btn.setToolTip(UI.TIP_GO_PAGE)
        self._page_go_btn.setMinimumWidth(68)
        self._page_go_btn.set_accent('#7b9edd')
        self._page_go_btn.clicked.connect(self._go_to_page_from_nav)
        dflow.add_widget(self._page_go_btn)

        self._doc_toolbar = dbar
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, dbar)


    # ── 탭 관리 ────────────────────────────────────────────────────

    _TAB_CLOSE_BTN_STYLE = (
        'QPushButton { font-size: 11px; font-weight: 700; border: none; border-radius: 3px;'
        '  background: transparent; color: #9ca3af; padding: 0; min-width: 16px; max-width: 16px;'
        '  min-height: 16px; max-height: 16px; }'
        'QPushButton:hover { background: #fca5a5; color: #ef4444; }'
        'QPushButton:pressed { background: #fecaca; }'
    )

    def _request_app_close(self):
        self._app_close_requested = True
        self.close()

    def _add_action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _open_calculator(self, mode: int = 0, legal_tab: int | None = None):
        from ui.dialogs.calculator_dialog import CalculatorDialog
        dlg = CalculatorDialog(mode, self)
        if mode == CalculatorDialog.MODE_LEGAL and legal_tab is not None:
            legal = dlg.legal_widget()
            if legal is not None:
                legal.set_tab(legal_tab)
        dlg.exec()

    # 문서 열림 관련 처리 ── ────────────────────────────────────────
    def _apply_permission_restrictions(self):
        """열람 암호로 연 권한 제한 문서는 인쇄/복사/편집을 앱에서도 막는다.
        (관리자 암호로 열면 doc.permissions 가 전체 허용이라 자동으로 풀린다.)"""
        import fitz as _fz
        doc = self._doc
        if not doc.is_open:
            return
        annot_ok = doc.can(_fz.PDF_PERM_ANNOTATE) or doc.can(_fz.PDF_PERM_MODIFY)
        self._perm_print_ok = doc.can(_fz.PDF_PERM_PRINT)
        self._perm_copy_ok = doc.can(_fz.PDF_PERM_COPY)
        # 편집/주석 도구 비활성
        if hasattr(self, '_annot_bar'):
            # 툴바 전체가 아니라 '도구 버튼'만 잠근다 — 같은 툴바에 얹힌
            # 저장·본문인식은 주석 권한과 무관하게 계속 쓸 수 있어야 한다
            self._annot_bar.set_tools_enabled(annot_ok)
        if hasattr(self, '_text_edit_btn'):
            self._text_edit_btn.setEnabled(annot_ok)
            if not annot_ok and self._text_edit_btn.isChecked():
                self._text_edit_btn.setChecked(False)
                self._canvas.set_text_edit_mode(False)
        # 캔버스 본문 편집도 차단
        if hasattr(self._canvas, 'set_edit_locked'):
            self._canvas.set_edit_locked(not annot_ok)
        # 안내 배너
        restr = []
        if not self._perm_print_ok:
            restr.append('인쇄')
        if not self._perm_copy_ok:
            restr.append('복사')
        if not annot_ok:
            restr.append('편집/주석')
        if restr:
            self._status_lbl.setText(
                '🔒 권한 제한 문서 — ' + ', '.join(restr) +
                ' 불가 (관리자 암호로 열면 전체 허용)')

    def _on_doc_opened(self, path: str):
        self._leave_text_draft_mode()
        name = Path(path).name if path else ' '
        ext = Path(path).suffix.lower() if path else ''
        is_image = ext in getattr(self, '_IMAGE_EXTS', set())
        if is_image:
            self.setWindowTitle(_cfg.window_title(f'{name} (PDF)'))
            self._status_lbl.setText(f' : {path}   PDF  [  ]')
        else:
            self.setWindowTitle(_cfg.window_title(name))
            self._status_lbl.setText(f': {path}' if path else ' ')
        self._canvas.discard_all_pending()
        self._renderer.invalidate_all()
        if self._thumbs.isVisible():
            self._thumbs.reload()
        self._reflow_active = False
        self._central_stack.setCurrentWidget(self._tab_widget)
        self._annot_bar.setVisible(True)
        # 탭 제목 업데이트
        self._update_current_tab_title()
        n = self._doc.page_count()
        if hasattr(self, '_page_spin'):
            self._page_spin.setMaximum(max(1, n))
            self._page_spin.setValue(1)
        view_mode = getattr(self, '_view_mode', UI.VIEW_SCROLL)
        if view_mode == UI.VIEW_SCROLL:
            self._canvas.show_scroll()
        elif view_mode in (UI.VIEW_DOUBLE, UI.VIEW_BOOK):
            self._canvas.show_double(0)
        else:
            self._canvas.show_page(0)
        QTimer.singleShot(50, self._actual_size)
        # 암호화 권한 제한 적용 (열람 암호로 연 경우 인쇄/복사/편집 차단)
        self._apply_permission_restrictions()
        # 서명된 문서면 서명자·시각·위변조 여부를 자동으로 알린다
        self._auto_verify_signatures_on_open()

    def _on_structure_changed(self):
        # 페이지 수/순서가 바뀌면 (index, zoom) 키 캐시가 전부 어긋나므로 전체 무효화
        self._renderer.invalidate_all()
        if self._thumbs.isVisible():
            self._thumbs.reload()
        self._canvas.refresh_page()
        self._refresh_note_panel()

    def _on_page_changed(self, idx: int):
        if self._text_draft_active:
            return
        n = self._doc.page_count()
        self._page_lbl.setText(f'{idx + 1} / {n}')
        if hasattr(self, '_page_spin'):
            self._page_spin.blockSignals(True)
            self._page_spin.setValue(idx + 1)
            self._page_spin.blockSignals(False)

    def _on_display_zoom_changed(self, zoom: float):
        """캔버스 표시 배율 변경 → 툴바 % 라벨 갱신."""
        if hasattr(self, '_zoom_pct_lbl'):
            self._zoom_pct_lbl.setText(f'{round(zoom * 100)}%')

    def _on_pending_count(self, count: int):
        if self._text_draft_active:
            self._pending_lbl.setText("")
            if hasattr(self, "_apply_btn"):
                self._apply_btn.setEnabled(False)
            if hasattr(self, "_discard_btn"):
                self._discard_btn.setEnabled(False)
            return
        self._pending_lbl.setText(f'미확정 {count}개' if count > 0 else '')
        if hasattr(self, "_apply_btn"):
            self._apply_btn.setEnabled(count > 0)
        if hasattr(self, "_discard_btn"):
            self._discard_btn.setEnabled(count > 0)

    def _on_doc_saved(self, path: str):
        """저장 완료 시 상태바 + 탭 제목 갱신."""
        self._status_lbl.setText(f'저장 완료: {path}')
        self._update_current_tab_title()

    def _on_annot_committed(self):
        if self._text_draft_active:
            return
        self._status_lbl.setText('PDF에 적용됨  (Ctrl+S로 저장)')
        QTimer.singleShot(2000, lambda: (
            self._status_lbl.setText(
                f': {self._doc.path}' if self._doc.path else ' ')
            if self._doc.is_open else None))
    def _confirm_discard(self) -> bool:
        if self._text_draft_active:
            if not self._text_draft.is_modified():
                return True
            msg = QMessageBox(self)
            msg.setWindowTitle('저장되지 않은 변경사항')
            msg.setText('새 문서 내용이 변경되었습니다. 저장할까요?')
            btn_save = msg.addButton('저장', QMessageBox.ButtonRole.AcceptRole)
            btn_discard = msg.addButton('버리기', QMessageBox.ButtonRole.DestructiveRole)
            msg.addButton('취소', QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(btn_save)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == btn_save:
                return self._save_text_draft(None)
            if clicked == btn_discard:
                return True
            return False

        pending_n = self._canvas.pending_layer().count()
        if self._doc.dirty or pending_n > 0:
            msg = QMessageBox(self)
            msg.setWindowTitle('저장되지 않은 변경사항')
            if pending_n > 0:
                msg.setText(f'저장되지 않은 변경사항과 미확정 어노테이션 {pending_n}개가 있습니다. 저장할까요?')
            else:
                msg.setText('저장되지 않은 변경사항이 있습니다. 저장할까요?')
            btn_save = msg.addButton('저장', QMessageBox.ButtonRole.AcceptRole)
            btn_discard = msg.addButton('버리기', QMessageBox.ButtonRole.DestructiveRole)
            msg.addButton('취소', QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(btn_save)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == btn_save:
                if not self._doc.path:
                    self._save_as()
                    return (not self._doc.dirty) and self._canvas.pending_layer().count() == 0
                return self._do_save(None)
            if clicked == btn_discard:
                return True
            return False
        return True

    # ── 드래그·드롭으로 파일 열기 ──────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            exts = {'.pdf','.png','.jpg','.jpeg','.bmp','.tiff','.tif','.webp','.gif'}
            if any(Path(u.toLocalFile()).suffix.lower() in exts for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        urls = [u.toLocalFile() for u in event.mimeData().urls()
                if Path(u.toLocalFile()).suffix.lower()
                   in {'.pdf','.png','.jpg','.jpeg','.bmp','.tiff','.tif','.webp','.gif'}]
        if not urls:
            return
        first, *rest = urls
        # 첫 번째 파일: 현재 탭이 빈 탭이면 현재 탭에, 아니면 새 탭에 열기
        # (위장 파일 검사는 open_path_checked / _new_tab 안에서 수행)
        if self._doc.is_open:
            self._new_tab(first)
        else:
            self.open_path_checked(first)
        # 나머지 파일은 각각 새 탭에
        for path in rest:
            self._new_tab(path)
        event.acceptProposedAction()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._book_view_active:
            self._toggle_book_view()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and getattr(self, '_view_mode', UI.VIEW_SINGLE) == UI.VIEW_SEGMENT:
            if hasattr(self, '_view_cb'):
                self._view_cb.blockSignals(True)
                self._view_cb.setCurrentText(UI.VIEW_SINGLE)
                self._view_cb.blockSignals(False)
            self._on_view_mode(UI.VIEW_SINGLE)
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_glass_buttons'):
            QTimer.singleShot(0, self._refresh_glass_backdrop_cache)

    def _confirm_all_tabs_for_close(self):
        """Ask about each modified PDF, including tabs that are not selected."""
        original = self._tab_widget.currentIndex()
        try:
            for idx, tab in enumerate(self._tabs):
                if tab.doc.is_open and (tab.doc.dirty or tab.canvas.pending_layer().count() > 0):
                    self._tab_widget.setCurrentIndex(idx)
                    if not self._confirm_discard():
                        return False
            return True
        finally:
            if original >= 0:
                self._tab_widget.setCurrentIndex(original)

    def closeEvent(self, event):
        if getattr(self, "_in_tab_close", False):
            event.ignore()
            return

        # 명시적 종료(파일>종료/Ctrl+Q) 외에는 사용자 확인 없이 앱을 닫지 않음
        if not getattr(self, "_app_close_requested", False):
            ans = QMessageBox.question(
                self,
                '종료 확인',
                '앱을 종료하시겠습니까?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self._app_close_requested = False
        if self._text_draft_active:
            if not self._confirm_discard():
                event.ignore()
                return
            self._leave_text_draft_mode()
            self._page_lbl.setText("")
            self._pending_lbl.setText("")
            self._status_lbl.setText(" ")
            self.setWindowTitle(_cfg.window_title())
            event.ignore()
            return
        # 여러 탭에 미저장 변경사항이 있는지 확인
        dirty_tabs = [
            tab for tab in self._tabs
            if tab.doc.is_open and (tab.doc.dirty or tab.canvas.pending_layer().count() > 0)
        ]
        if dirty_tabs:
            if not self._confirm_all_tabs_for_close():
                event.ignore()
                return
        # 자동 저장 타이머 즉시 중단 — emergency_save와 충돌 방지
        if hasattr(self, '_autosave_timer'):
            self._autosave_timer.stop()
        # 백그라운드 warmup 스레드 — 200ms만 기다리고 종료
        # (setExpiryTimeout(0)으로 유휴 스레드는 이미 해제된 상태)
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(20)
        self._settings.window_w = self.width()
        self._settings.window_h = self.height()
        self._settings.save()
        if self._doc.is_open and (self._doc.dirty or self._canvas.pending_layer().count() > 0):
            self._emergency_save()
        else:
            self._clear_autosave()
        # Stop render workers/timers before Qt destroys their canvases.
        for tab in self._tabs:
            self._prepare_pdf_tab_for_close(tab)
        import os as _os
        for _tmp in getattr(self, '_snapshot_tmp_files', []):
            try:
                if _os.path.exists(_tmp):
                    _os.remove(_tmp)
            except Exception:
                swallowed()
        event.accept()
