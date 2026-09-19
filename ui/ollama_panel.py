# ui/ollama_panel.py — Ollama 분석 창 (요약·Q&A·용어추출·교정·어노테이션)
from __future__ import annotations
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QComboBox, QProgressBar, QFrame, QTabWidget,
    QRadioButton, QButtonGroup, QSpinBox, QApplication,
)
from utils.settings import AppSettings
from utils.errlog import swallowed

_LENGTH_MAP  = {'짧게': 'short', '보통': 'medium', '자세히': 'long'}
_TERM_MAP    = {'전문 용어': 'technical', '인명·기관': 'entities',
                '날짜·수치': 'numbers', '모두': 'all'}
_ANNOT_MAP   = {'설명': 'explain', '요약': 'summary', '비평': 'critique'}
_CORRECT_TYPES = ['OCR 오류 보정', '번역 다듬기', '표 구조화']

# ── 라이트 테마 스타일시트 ────────────────────────────────────────────
_STYLE = """
OllamaAnalysisWindow, OllamaAnalysisWindow > QWidget {
    background-color: #ffffff;
    color: #1e2532;
}
QWidget {
    background-color: #ffffff;
    color: #1e2532;
    font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 13px;
}
/* ── 입력 / 출력 텍스트 영역 ── */
QTextEdit {
    background-color: #f5f7ff;
    color: #1e2532;
    border: 1.5px solid #c5d0f8;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #4361ee;
    selection-color: #ffffff;
}
QTextEdit:focus {
    border: 1.5px solid #4361ee;
    background-color: #f8f9ff;
}
QTextEdit[readOnly="true"] {
    background-color: #f8f9ff;
    border-color: #dde4f8;
}
/* ── 버튼 기본 ── */
QPushButton {
    background-color: #ffffff;
    color: #2e3555;
    border: 1.5px solid #c5d0f8;
    border-radius: 5px;
    padding: 5px 14px;
    font-weight: 600;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #eef2ff;
    border-color: #4361ee;
    color: #4361ee;
}
QPushButton:pressed {
    background-color: #4361ee;
    color: #ffffff;
    border-color: #3451d1;
}
QPushButton:disabled {
    background-color: #f5f7ff;
    color: #b0b8cc;
    border-color: #e0e8ff;
}
/* ── 실행 버튼 (파랑) ── */
QPushButton#btn_primary {
    background-color: #4361ee;
    color: #ffffff;
    border: none;
    font-size: 14px;
    padding: 6px 20px;
    border-radius: 6px;
}
QPushButton#btn_primary:hover  { background-color: #5573f0; }
QPushButton#btn_primary:pressed { background-color: #3350d4; }
QPushButton#btn_primary:disabled {
    background-color: #c5d0f8;
    color: #8090cc;
}
/* ── 전송 버튼 (초록) ── */
QPushButton#btn_send {
    background-color: #f0fff4;
    color: #1e7a48;
    border: 1.5px solid #6fcf97;
    font-size: 14px;
    padding: 6px 18px;
    border-radius: 6px;
}
QPushButton#btn_send:hover {
    background-color: #d4f5e2;
    color: #155a34;
    border-color: #3db86a;
}
QPushButton#btn_send:disabled {
    background-color: #f5f5f5;
    color: #a8c8b4;
    border-color: #d0e8d8;
}
/* ── 초기화 버튼 (빨강) ── */
QPushButton#btn_danger {
    background-color: #fff5f7;
    color: #d63060;
    border: 1.5px solid #f5a0b5;
    border-radius: 5px;
}
QPushButton#btn_danger:hover {
    background-color: #ffe0e8;
    color: #b0204a;
    border-color: #d63060;
}
/* ── 아이콘 버튼 ── */
QPushButton#btn_icon {
    background-color: transparent;
    border: 1.5px solid #c5d0f8;
    border-radius: 4px;
    padding: 3px;
    min-height: 22px;
    max-height: 26px;
}
QPushButton#btn_icon:hover {
    background-color: #eef2ff;
    border-color: #4361ee;
}
/* ── 콤보박스 ── */
QComboBox {
    background-color: #ffffff;
    color: #1e2532;
    border: 1.5px solid #c5d0f8;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 26px;
}
QComboBox:hover { border-color: #4361ee; }
QComboBox:focus { border-color: #4361ee; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1e2532;
    selection-background-color: #eef2ff;
    selection-color: #4361ee;
    border: 1.5px solid #c5d0f8;
    outline: none;
}
/* ── 탭 ── */
QTabWidget::pane {
    border: 1.5px solid #c5d0f8;
    border-top: none;
    background-color: #ffffff;
    border-radius: 0 0 7px 7px;
}
QTabWidget::tab-bar { alignment: left; }
QTabBar { background-color: transparent; }
QTabBar::tab {
    background-color: #eef2ff;
    color: #7080b8;
    border: 1.5px solid #c5d0f8;
    border-bottom: none;
    border-radius: 5px 5px 0 0;
    padding: 5px 12px;
    margin-right: 2px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #4361ee;
    border-color: #c5d0f8;
    font-weight: 700;
    border-bottom: 2px solid #ffffff;
}
QTabBar::tab:hover:!selected {
    background-color: #e0e8ff;
    color: #4361ee;
}
/* ── 라벨 ── */
QLabel {
    color: #4a5278;
    background: transparent;
}
QLabel#lbl_section {
    color: #4361ee;
    font-weight: 700;
    font-size: 12px;
    background: transparent;
}
QLabel#lbl_status_ok  { color: #1a7a48; font-weight: 600; }
QLabel#lbl_status_err { color: #d63060; font-weight: 600; }
/* ── 프로그레스바 ── */
QProgressBar {
    background-color: #eef2ff;
    border: none;
    border-radius: 3px;
    max-height: 5px;
}
QProgressBar::chunk {
    background-color: #4361ee;
    border-radius: 3px;
}
/* ── 스크롤바 ── */
QScrollBar:vertical {
    background-color: #f5f7ff;
    width: 8px;
    border-radius: 4px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: #c5d0f8;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background-color: #4361ee; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background-color: #f5f7ff;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #c5d0f8;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background-color: #4361ee; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
/* ── 라디오 버튼 ── */
QRadioButton {
    color: #1e2532;
    spacing: 6px;
    background: transparent;
}
QRadioButton::indicator {
    width: 14px; height: 14px;
    border: 2px solid #c5d0f8;
    border-radius: 7px;
    background-color: #ffffff;
}
QRadioButton::indicator:checked {
    background-color: #4361ee;
    border-color: #4361ee;
}
QRadioButton::indicator:hover { border-color: #4361ee; }
/* ── 스핀박스 ── */
QSpinBox {
    background-color: #ffffff;
    color: #1e2532;
    border: 1.5px solid #c5d0f8;
    border-radius: 4px;
    padding: 3px 6px;
}
QSpinBox:focus { border-color: #4361ee; }
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #eef2ff;
    border: none;
    width: 14px;
}
/* ── 구분선 ── */
QFrame[frameShape="4"], QFrame[frameShape="HLine"] {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 transparent, stop:0.15 #c5d0f8,
        stop:0.85 #c5d0f8, stop:1 transparent);
    border: none;
    max-height: 1px;
}
"""

# ── HTML 채팅 렌더러 ────────────────────────────────────────────────────

def _chat_html(history: list[dict], placeholder: str = '') -> str:
    """대화 이력을 Qt HTML 말풍선 스타일로 렌더링한다."""
    if not history:
        if placeholder:
            return (
                '<html><body style="background-color:#f8f9ff;color:#b0b8cc;'
                'font-family:Malgun Gothic,sans-serif;font-size:13px;padding:12px;">'
                f'<p style="color:#b0b8cc;font-style:italic;">{placeholder}</p>'
                '</body></html>'
            )
        return ''

    parts = [
        '<html><body style="background-color:#f8f9ff;'
        'font-family:\'Malgun Gothic\',\'Segoe UI\',sans-serif;font-size:13px;margin:0;padding:6px;">'
    ]
    for msg in history:
        is_user = msg['role'] == 'user'
        content = (
            msg['content']
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('\n', '<br/>')
        )
        if is_user:
            parts.append(
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:5px 0;">'
                '<tr><td align="right">'
                '<table cellspacing="0" cellpadding="0">'
                '<tr><td style="background-color:#eef2ff;color:#1e2532;'
                'border-left:3px solid #4361ee;border-radius:2px;'
                'padding:7px 12px;font-size:13px;">'
                f'<span style="color:#4361ee;font-weight:700;font-size:11px;">나</span>'
                f'<br/>{content}'
                '</td></tr></table>'
                '</td></tr></table>'
            )
        else:
            parts.append(
                '<table width="100%" cellspacing="0" cellpadding="0" style="margin:5px 0;">'
                '<tr><td align="left">'
                '<table cellspacing="0" cellpadding="0">'
                '<tr><td style="background-color:#f0fff4;color:#1e2532;'
                'border-left:3px solid #3db86a;border-radius:2px;'
                'padding:7px 12px;font-size:13px;">'
                f'<span style="color:#1a7a48;font-weight:700;font-size:11px;">🦙 Ollama</span>'
                f'<br/>{content}'
                '</td></tr></table>'
                '</td></tr></table>'
            )
    parts.append('</body></html>')
    return ''.join(parts)


def _mk_label(text: str, section: bool = False) -> QLabel:
    lbl = QLabel(text)
    if section:
        lbl.setObjectName('lbl_section')
    return lbl


class OllamaAnalysisWindow(QWidget):
    """Ollama 로컬 LLM을 활용한 문서 분석 창."""

    def __init__(self, settings: AppSettings,
                 page_callbacks: dict | None = None,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle('🦙 Ollama 분석')
        self.resize(720, 860)
        self.setStyleSheet(_STYLE)
        self._settings       = settings
        self._page_callbacks = page_callbacks
        self._pool           = QThreadPool.globalInstance()
        self._qa_history: list[dict]   = []
        self._qa_context: str          = ''
        self._chat_history: list[dict] = []
        self._active_signals: list     = []

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 12)

        # ── 모델 행 ──────────────────────────────────────────────────
        lay.addWidget(self._build_model_row())

        # ── Ollama 미설치 안내 배너 ───────────────────────────────────
        self._install_banner = self._build_install_banner()
        self._install_banner.setVisible(False)
        lay.addWidget(self._install_banner)

        # ── 탭 ───────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_summary_tab(), '📝 요약')
        self._tabs.addTab(self._build_qa_tab(),      '💬 Q&A')
        self._tabs.addTab(self._build_terms_tab(),   '🔍 용어')
        self._tabs.addTab(self._build_correct_tab(), '✏ 교정')
        self._tabs.addTab(self._build_ocr_tab(),     '🧾 OCR')
        self._tabs.addTab(self._build_annot_tab(),   '📌 어노테이션')
        self._tabs.addTab(self._build_chat_tab(),    '🗣 대화')
        self._tabs.addTab(self._build_translate_tab(), '🌐 번역')
        lay.addWidget(self._tabs, stretch=1)

        # ── 실행 버튼 행 ─────────────────────────────────────────────
        run_row = QHBoxLayout()
        self._run_btn = QPushButton('▶  실행')
        self._run_btn.setObjectName('btn_primary')
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._run)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        lay.addLayout(run_row)

        # ── 진행 / 상태 ──────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setMaximum(0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status_lbl = QLabel('')
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            'color:#4361ee; font-size:12px; background:transparent;')
        lay.addWidget(self._status_lbl)

        # ── 구분선 + 결과 영역 헤더 ──────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        res_hdr = QHBoxLayout()
        res_hdr.addWidget(_mk_label('결과', section=True))
        res_hdr.addStretch()
        copy_btn = QPushButton('📋')
        copy_btn.setObjectName('btn_icon')
        copy_btn.setFixedWidth(30)
        copy_btn.setToolTip('결과 복사')
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._output.toPlainText()))
        clr_btn = QPushButton('🗑')
        clr_btn.setObjectName('btn_icon')
        clr_btn.setFixedWidth(30)
        clr_btn.setToolTip('결과 지우기')
        clr_btn.clicked.connect(lambda: self._output.clear())
        res_hdr.addWidget(copy_btn)
        res_hdr.addWidget(clr_btn)
        lay.addLayout(res_hdr)

        self._output = QTextEdit()
        self._output.setReadOnly(False)
        self._output.setPlaceholderText('분석 결과가 여기에 표시됩니다.')
        self._output.setMinimumHeight(120)
        lay.addWidget(self._output, stretch=1)

        QTimer.singleShot(400, self._refresh_models)

    # ── 모델 행 빌더 ─────────────────────────────────────────────────

    def _build_model_row(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet(
            'QWidget { background-color: #f0f4ff; border-radius: 7px; '
            'border: 1.5px solid #c5d0f8; padding: 4px 6px; }')
        row = QHBoxLayout(container)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        lbl = QLabel('모델')
        lbl.setStyleSheet('color:#4361ee; font-weight:700; '
                          'background:transparent; font-size:12px;')
        row.addWidget(lbl)

        self._model_cb = QComboBox()
        self._model_cb.setMinimumWidth(200)
        self._model_cb.setToolTip('노트북 권장 기본 모델: gemma4:e4b')
        row.addWidget(self._model_cb, stretch=2)

        self._refresh_btn = QPushButton('🔄')
        self._refresh_btn.setObjectName('btn_icon')
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.setToolTip('모델 목록 새로고침')
        self._refresh_btn.clicked.connect(self._refresh_models)
        row.addWidget(self._refresh_btn)

        self._conn_lbl = QLabel('⚪ 확인 중…')
        self._conn_lbl.setStyleSheet(
            'color:#8090b8; font-size:11px; background:transparent;')
        row.addWidget(self._conn_lbl)
        row.addStretch()
        return container

    # ── Ollama 설치 안내 배너 ────────────────────────────────────────

    def _build_install_banner(self) -> QWidget:
        banner = QFrame()
        banner.setStyleSheet(
            'QFrame { background-color: #fff8e6; border: 1.5px solid #f0c040;'
            ' border-radius: 8px; }'
            'QLabel { background: transparent; color: #7a5500; }'
            'QPushButton { background: #4361ee; color: #fff; border: none;'
            ' border-radius: 5px; padding: 4px 14px; font-weight: 700; }'
            'QPushButton:hover { background: #5573f0; }'
        )
        vlay = QVBoxLayout(banner)
        vlay.setContentsMargins(14, 10, 14, 10)
        vlay.setSpacing(6)

        title = QLabel('🦙  Ollama가 실행되지 않고 있습니다')
        title.setStyleSheet('font-weight: 700; font-size: 13px;'
                            ' color: #7a5500; background: transparent;')
        vlay.addWidget(title)

        desc = QLabel(
            'Ollama는 LLM(대형 언어 모델)을 내 PC에서 직접 실행하는 무료 오픈소스 프로그램입니다.\n'
            '요약·Q&A·교정·대화 기능을 쓰려면 Ollama를 먼저 설치하고 실행해야 합니다.'
        )
        desc.setWordWrap(True)
        desc.setStyleSheet('font-size: 12px; color: #7a5500; background: transparent;')
        vlay.addWidget(desc)

        step = QLabel(
            '① ollama.com 에서 Windows용 설치 파일 다운로드 후 설치\n'
            '② 설치 후 자동으로 백그라운드에서 실행됩니다\n'
            '③ 모델 설치 예시:  ollama pull gemma4:e4b\n'
            '④ 설치 완료 후 위 🔄 버튼을 눌러 새로고침하세요'
        )
        step.setWordWrap(True)
        step.setStyleSheet('font-size: 12px; color: #5a4000; background: transparent;')
        vlay.addWidget(step)

        btn_row = QHBoxLayout()
        dl_btn = QPushButton('🌐  ollama.com 열기')
        dl_btn.clicked.connect(
            lambda: __import__('webbrowser').open('https://ollama.com/download'))
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        vlay.addLayout(btn_row)

        return banner

    # ── 탭 빌더 헬퍼 ─────────────────────────────────────────────────

    def _make_page_selector(self) -> tuple[QWidget, callable]:
        container = QWidget()
        container.setStyleSheet('QWidget { background: transparent; }')
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(3)

        grp   = QButtonGroup(container)
        r_cur = QRadioButton('현재 페이지')
        r_all = QRadioButton('전체 페이지')
        r_rng = QRadioButton('범위 지정')
        r_cur.setChecked(True)
        grp.addButton(r_cur, 0)
        grp.addButton(r_all, 1)
        grp.addButton(r_rng, 2)

        radio_row = QHBoxLayout()
        for r in (r_cur, r_all, r_rng):
            radio_row.addWidget(r)
        radio_row.addStretch()
        vlay.addLayout(radio_row)

        rng_w   = QWidget()
        rng_w.setStyleSheet('QWidget { background: transparent; }')
        rng_lay = QHBoxLayout(rng_w)
        rng_lay.setContentsMargins(0, 0, 0, 0)
        rng_lay.addWidget(QLabel('페이지:'))
        from_spin = QSpinBox(); from_spin.setMinimum(1); from_spin.setMaximum(9999)
        to_spin   = QSpinBox(); to_spin.setMinimum(1);   to_spin.setMaximum(9999)
        rng_lay.addWidget(from_spin)
        rng_lay.addWidget(QLabel('~'))
        rng_lay.addWidget(to_spin)
        rng_lay.addStretch()
        rng_w.setVisible(False)
        vlay.addWidget(rng_w)
        r_rng.toggled.connect(rng_w.setVisible)

        def get_pages() -> list[int]:
            if not self._page_callbacks or not self._page_callbacks['is_open']():
                return []
            n = self._page_callbacks['page_count']()
            if r_cur.isChecked():
                return [self._page_callbacks['current_page']()]
            if r_all.isChecked():
                return list(range(n))
            fp = max(1, min(from_spin.value(), n))
            tp = max(fp, min(to_spin.value(), n))
            return list(range(fp - 1, tp))

        return container, get_pages

    # ── 각 탭 빌더 ───────────────────────────────────────────────────

    def _build_summary_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('페이지 범위', section=True))
        pg_w, self._summary_pages = self._make_page_selector()
        lay.addWidget(pg_w)
        lay.addSpacing(4)
        len_row = QHBoxLayout()
        len_row.addWidget(QLabel('요약 길이:'))
        self._summary_len_cb = QComboBox()
        self._summary_len_cb.addItems(list(_LENGTH_MAP.keys()))
        self._summary_len_cb.setCurrentText('보통')
        len_row.addWidget(self._summary_len_cb)
        len_row.addStretch()
        lay.addLayout(len_row)
        lay.addStretch()
        return tab

    def _build_qa_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('페이지 범위', section=True))
        pg_w, self._qa_pages = self._make_page_selector()
        lay.addWidget(pg_w)
        lay.addSpacing(4)
        lay.addWidget(_mk_label('질문', section=True))
        self._qa_input = QTextEdit()
        self._qa_input.setMaximumHeight(68)
        self._qa_input.setPlaceholderText('문서에 대해 질문하세요…  (Ctrl+Enter: 전송)')
        _sc_qa = QShortcut(QKeySequence('Ctrl+Return'), self._qa_input)
        _sc_qa.activated.connect(self._run_qa)
        lay.addWidget(self._qa_input)

        btn_row = QHBoxLayout()
        self._qa_ask_btn = QPushButton('▶  질문하기')
        self._qa_ask_btn.setObjectName('btn_send')
        self._qa_ask_btn.setEnabled(False)
        self._qa_ask_btn.clicked.connect(self._run_qa)
        clr_btn = QPushButton('🗑  초기화')
        clr_btn.setObjectName('btn_danger')
        clr_btn.clicked.connect(self._clear_qa)
        btn_row.addWidget(self._qa_ask_btn)
        btn_row.addWidget(clr_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        lay.addWidget(_mk_label('대화 내역', section=True))
        self._qa_display = QTextEdit()
        self._qa_display.setReadOnly(True)
        self._qa_display.setHtml(_chat_html([], '질문하면 여기에 대화가 쌓입니다.'))
        lay.addWidget(self._qa_display, stretch=2)
        return tab

    def _build_terms_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('페이지 범위', section=True))
        pg_w, self._terms_pages = self._make_page_selector()
        lay.addWidget(pg_w)
        lay.addSpacing(4)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel('추출 유형:'))
        self._terms_type_cb = QComboBox()
        self._terms_type_cb.addItems(list(_TERM_MAP.keys()))
        self._terms_type_cb.setCurrentText('모두')
        type_row.addWidget(self._terms_type_cb)
        type_row.addStretch()
        lay.addLayout(type_row)
        lay.addStretch()
        return tab

    def _build_correct_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel('교정 유형:'))
        self._correct_type_cb = QComboBox()
        self._correct_type_cb.addItems(_CORRECT_TYPES)
        type_row.addWidget(self._correct_type_cb)
        type_row.addStretch()
        lay.addLayout(type_row)
        lay.addWidget(_mk_label('교정할 텍스트', section=True))
        self._correct_input = QTextEdit()
        self._correct_input.setPlaceholderText('교정할 텍스트를 붙여넣으세요.')
        lay.addWidget(self._correct_input, stretch=2)
        btn_row = QHBoxLayout()
        clr_btn = QPushButton('🗑  지우기')
        clr_btn.setObjectName('btn_danger')
        clr_btn.clicked.connect(self._correct_input.clear)
        btn_row.addWidget(clr_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return tab

    def _build_ocr_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('페이지 범위', section=True))
        pg_w, self._ocr_pages = self._make_page_selector()
        lay.addWidget(pg_w)
        lay.addSpacing(4)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel('OCR 언어:'))
        self._ocr_lang_cb = QComboBox()
        self._ocr_lang_cb.addItems(['한국어', '영어', '일본어', '중국어(간체)'])
        self._ocr_lang_cb.setCurrentText('한국어')
        self._ocr_lang_cb.setToolTip('Ollama Vision OCR에 전달할 기본 언어 힌트')
        lang_row.addWidget(self._ocr_lang_cb)
        lang_row.addStretch()
        lay.addLayout(lang_row)

        hint = QLabel('스캔 페이지는 이미지로 OCR하고, 텍스트 PDF 페이지는 내장 텍스트를 그대로 가져옵니다.')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return tab

    def _build_annot_tab(self) -> QWidget:
        tab, lay = self._make_tab()
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel('어노테이션 유형:'))
        self._annot_style_cb = QComboBox()
        self._annot_style_cb.addItems(list(_ANNOT_MAP.keys()))
        style_row.addWidget(self._annot_style_cb)
        style_row.addStretch()
        lay.addLayout(style_row)

        src_grp = QButtonGroup(tab)
        self._annot_r_page = QRadioButton('현재 페이지')
        self._annot_r_text = QRadioButton('직접 입력')
        self._annot_r_page.setChecked(True)
        src_grp.addButton(self._annot_r_page, 0)
        src_grp.addButton(self._annot_r_text, 1)
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel('소스:'))
        src_row.addWidget(self._annot_r_page)
        src_row.addWidget(self._annot_r_text)
        src_row.addStretch()
        lay.addLayout(src_row)

        self._annot_input = QTextEdit()
        self._annot_input.setPlaceholderText('어노테이션을 생성할 텍스트를 입력하세요.')
        self._annot_input.setVisible(False)
        self._annot_r_text.toggled.connect(self._annot_input.setVisible)
        lay.addWidget(self._annot_input, stretch=2)
        lay.addStretch()
        return tab

    def _build_chat_tab(self) -> QWidget:
        """PDF와 무관한 자유 대화 탭."""
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('대화 내역', section=True))
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setHtml(_chat_html(
            [], 'Ollama와 자유롭게 대화할 수 있습니다.\nPDF와 무관한 일반 질문도 가능합니다.'))
        lay.addWidget(self._chat_display, stretch=3)

        lay.addWidget(_mk_label('메시지', section=True))
        self._chat_input = QTextEdit()
        self._chat_input.setMaximumHeight(72)
        self._chat_input.setPlaceholderText('메시지를 입력하세요…  (Ctrl+Enter: 전송)')
        lay.addWidget(self._chat_input)

        _sc = QShortcut(QKeySequence('Ctrl+Return'), self._chat_input)
        _sc.activated.connect(self._run_chat)

        btn_row = QHBoxLayout()
        self._chat_ask_btn = QPushButton('▶  전송')
        self._chat_ask_btn.setObjectName('btn_send')
        self._chat_ask_btn.setEnabled(False)
        self._chat_ask_btn.clicked.connect(self._run_chat)
        clr_btn = QPushButton('🗑  초기화')
        clr_btn.setObjectName('btn_danger')
        clr_btn.clicked.connect(self._clear_chat)
        btn_row.addWidget(self._chat_ask_btn)
        btn_row.addWidget(clr_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return tab

    @staticmethod
    def _make_tab() -> tuple[QWidget, QVBoxLayout]:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(7)
        return tab, lay

    # ── 모델 새로고침 ─────────────────────────────────────────────────

    def _refresh_models(self):
        from utils.ollama_client import is_running, get_text_models
        self._refresh_btn.setEnabled(False)
        try:
            if not is_running():
                self._model_cb.clear()
                self._conn_lbl.setText('🔴 Ollama 미실행')
                self._conn_lbl.setStyleSheet(
                    'color:#d63060; font-size:11px; background:transparent;')
                self._run_btn.setEnabled(False)
                self._qa_ask_btn.setEnabled(False)
                self._chat_ask_btn.setEnabled(False)
                self._install_banner.setVisible(True)
                return
            self._install_banner.setVisible(False)
            models = get_text_models()
            self._model_cb.clear()
            if models:
                self._model_cb.addItems(models)
                for i, m in enumerate(models):
                    if m.startswith('──'):
                        item = self._model_cb.model().item(i)
                        if item:
                            item.setEnabled(False)
                count = sum(1 for m in models if not m.startswith('──'))
                self._conn_lbl.setText(f'🟢 연결됨 — {count}개 모델')
                self._conn_lbl.setStyleSheet(
                    'color:#1a7a48; font-size:11px; background:transparent;')
                self._run_btn.setEnabled(True)
                self._qa_ask_btn.setEnabled(True)
                self._chat_ask_btn.setEnabled(True)
            else:
                self._conn_lbl.setText('🟡 모델 없음')
                self._conn_lbl.setStyleSheet(
                    'color:#b07800; font-size:11px; background:transparent;')
                self._run_btn.setEnabled(False)
                self._qa_ask_btn.setEnabled(False)
                self._chat_ask_btn.setEnabled(False)
        finally:
            self._refresh_btn.setEnabled(True)

    # ── 번역 탭 ──────────────────────────────────────────────────────

    def _build_translate_tab(self) -> QWidget:
        from utils.translate_text_utils import LANG_PAIRS
        tab, lay = self._make_tab()
        lay.addWidget(_mk_label('페이지 범위', section=True))
        pg_w, self._trans_pages = self._make_page_selector()
        lay.addWidget(pg_w)
        lay.addSpacing(4)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel('번역 방향:'))
        self._trans_lang_cb = QComboBox()
        self._trans_lang_cb.addItems(LANG_PAIRS.keys())
        saved = getattr(self._settings, 'translate_lang', '')
        if saved in LANG_PAIRS:
            self._trans_lang_cb.setCurrentText(saved)
        dir_row.addWidget(self._trans_lang_cb)
        dir_row.addStretch()
        lay.addLayout(dir_row)

        hint = QLabel(
            '💡 텍스트 직접 입력·스캔본 OCR 번역·ChatGPT/Claude API·웹 AI 는 '
            '번역 허브(Ctrl+Shift+H)에서 사용할 수 있습니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#6b7280; font-size:11px; background:transparent;')
        lay.addWidget(hint)
        lay.addStretch()
        return tab

    def _run_translate(self):
        model = self._get_model()
        if not model:
            return
        text = self._page_text(self._trans_pages)
        if not text:
            self._status_lbl.setText(
                '⚠ PDF에서 텍스트를 가져올 수 없습니다. '
                '(스캔본은 번역 허브의 페이지 번역을 사용하세요)')
            return
        from utils.translate_text_utils import LANG_PAIRS
        src, tgt = LANG_PAIRS[self._trans_lang_cb.currentText()]
        self._settings.translate_lang = self._trans_lang_cb.currentText()
        self._settings.save()
        from utils.ollama_client import translate_long
        self._start_worker(translate_long, text, src, tgt, model,
                           status='번역 중…')

    # ── 텍스트 추출 헬퍼 ─────────────────────────────────────────────

    def _get_model(self) -> str | None:
        m = self._model_cb.currentText()
        return None if (not m or m.startswith('──')) else m

    def _page_text(self, get_pages_fn) -> str:
        pages = get_pages_fn()
        if not pages or not self._page_callbacks:
            return ''
        data = self._page_callbacks['get_page_data'](pages)
        return '\n\n'.join(d for _, d in data if isinstance(d, str) and d.strip())

    # ── 실행 디스패처 ────────────────────────────────────────────────

    def _run(self):
        tab = self._tabs.currentIndex()
        if tab == 0:   self._run_summary()
        elif tab == 2: self._run_terms()
        elif tab == 3: self._run_correct()
        elif tab == 4: self._run_ocr()
        elif tab == 5: self._run_annot()
        elif tab == 6: self._run_chat()
        elif tab == 7: self._run_translate()

    def _start_worker(self, fn, *args, status: str = 'Ollama 처리 중…', **kwargs):
        from workers.ollama_analysis_worker import OllamaAnalysisWorker
        self._set_busy(True)
        worker = OllamaAnalysisWorker(fn, *args, status_msg=status, **kwargs)
        sigs = worker.signals
        self._active_signals.append(sigs)
        def _release(_, s=sigs):
            try: self._active_signals.remove(s)
            except ValueError: pass
        sigs.status.connect(self._status_lbl.setText)
        sigs.finished.connect(self._on_done)
        sigs.finished.connect(_release)
        sigs.error.connect(self._on_error)
        sigs.error.connect(_release)
        self._pool.start(worker)

    def _run_summary(self):
        model = self._get_model()
        if not model: return
        text = self._page_text(self._summary_pages)
        if not text:
            self._status_lbl.setText('⚠ PDF에서 텍스트를 가져올 수 없습니다.')
            return
        length = _LENGTH_MAP.get(self._summary_len_cb.currentText(), 'medium')
        from utils.ollama_client import summarize
        self._start_worker(summarize, text, model, length, status='요약 중…')

    def _run_qa(self):
        model = self._get_model()
        if not model: return
        question = self._qa_input.toPlainText().strip()
        if not question:
            self._status_lbl.setText('⚠ 질문을 입력하세요.')
            return
        fresh = self._page_text(self._qa_pages)
        if fresh:
            self._qa_context = fresh
        if not self._qa_context:
            self._status_lbl.setText('⚠ 문서 컨텍스트를 가져올 수 없습니다.')
            return
        from workers.ollama_analysis_worker import OllamaAnalysisWorker
        from utils.ollama_client import qa
        self._set_busy(True)
        history_copy = list(self._qa_history)
        worker = OllamaAnalysisWorker(
            qa, self._qa_context, question, model, history_copy,
            status_msg='질문 답변 중…')
        sigs = worker.signals
        self._active_signals.append(sigs)
        def _release_qa(_, s=sigs):
            try: self._active_signals.remove(s)
            except ValueError: pass
        sigs.status.connect(self._status_lbl.setText)
        sigs.finished.connect(lambda ans: self._on_qa_done(question, ans))
        sigs.finished.connect(_release_qa)
        sigs.error.connect(self._on_error)
        sigs.error.connect(_release_qa)
        self._pool.start(worker)

    def _run_chat(self):
        model = self._get_model()
        if not model: return
        question = self._chat_input.toPlainText().strip()
        if not question:
            self._status_lbl.setText('⚠ 메시지를 입력하세요.')
            return
        from workers.ollama_analysis_worker import OllamaAnalysisWorker
        from utils.ollama_client import free_chat
        self._set_busy(True)
        history_copy = list(self._chat_history)
        worker = OllamaAnalysisWorker(
            free_chat, question, model, history_copy,
            status_msg='답변 생성 중…')
        sigs = worker.signals
        self._active_signals.append(sigs)
        def _release_chat(_, s=sigs):
            try: self._active_signals.remove(s)
            except ValueError: pass
        sigs.status.connect(self._status_lbl.setText)
        sigs.finished.connect(lambda ans: self._on_chat_done(question, ans))
        sigs.finished.connect(_release_chat)
        sigs.error.connect(self._on_error)
        sigs.error.connect(_release_chat)
        self._pool.start(worker)

    def _run_terms(self):
        model = self._get_model()
        if not model: return
        text = self._page_text(self._terms_pages)
        if not text:
            self._status_lbl.setText('⚠ PDF에서 텍스트를 가져올 수 없습니다.')
            return
        mode = _TERM_MAP.get(self._terms_type_cb.currentText(), 'all')
        from utils.ollama_client import extract_terms
        self._start_worker(extract_terms, text, model, mode, status='용어 추출 중…')

    def _run_correct(self):
        model = self._get_model()
        if not model: return
        text = self._correct_input.toPlainText().strip()
        if not text:
            self._status_lbl.setText('⚠ 교정할 텍스트를 입력하세요.')
            return
        ctype = self._correct_type_cb.currentText()
        if ctype == 'OCR 오류 보정':
            from utils.ollama_client import correct_ocr
            self._start_worker(correct_ocr, text, model, status='OCR 오류 보정 중…')
        elif ctype == '번역 다듬기':
            from utils.ollama_client import improve_translation
            self._start_worker(improve_translation, text, 'ko', model, status='번역 다듬기 중…')
        else:
            from utils.ollama_client import structure_table
            self._start_worker(structure_table, text, model, status='표 구조화 중…')

    def _run_ocr(self):
        model = self._get_model()
        if not model:
            return
        if not self._page_callbacks or not self._page_callbacks['is_open']():
            self._status_lbl.setText('⚠ PDF를 먼저 열어 주세요.')
            return

        pages = self._ocr_pages()
        if not pages:
            self._status_lbl.setText('⚠ OCR할 페이지를 선택하세요.')
            return

        data = self._page_callbacks['get_page_data'](pages)
        text_pages: dict[int, str] = {}
        image_pages: list[tuple[int, object]] = []
        for page_idx, payload in data:
            if isinstance(payload, str):
                text = payload.strip()
                if text:
                    text_pages[page_idx] = text
            else:
                image_pages.append((page_idx, payload))

        if not text_pages and not image_pages:
            self._status_lbl.setText('⚠ OCR할 페이지 데이터를 가져오지 못했습니다.')
            return

        if not image_pages:
            self._on_ollama_ocr_done(text_pages)
            return

        lang_map = {
            '한국어': 'ko',
            '영어': 'en',
            '일본어': 'ja',
            '중국어(간체)': 'zh',
        }
        lang = lang_map.get(self._ocr_lang_cb.currentText(), 'ko')

        from workers.ollama_worker import OllamaOcrWorker
        self._set_busy(True)
        worker = OllamaOcrWorker(image_pages, model, lang=lang)
        sigs = worker.signals
        self._active_signals.append(sigs)

        def _release(_, s=sigs):
            try:
                self._active_signals.remove(s)
            except ValueError:
                swallowed()

        sigs.status.connect(self._status_lbl.setText)
        sigs.progress.connect(
            lambda done, total: (
                self._progress.setMaximum(total),
                self._progress.setValue(done),
            )
        )
        sigs.finished.connect(lambda result, base=text_pages: self._on_ollama_ocr_done({**base, **result}))
        sigs.finished.connect(_release)
        sigs.error.connect(self._on_error)
        sigs.error.connect(_release)
        self._pool.start(worker)

    def _run_annot(self):
        model = self._get_model()
        if not model: return
        if self._annot_r_page.isChecked():
            if self._page_callbacks and self._page_callbacks['is_open']():
                cur  = self._page_callbacks['current_page']()
                data = self._page_callbacks['get_page_data']([cur])
                text = '\n\n'.join(d for _, d in data if isinstance(d, str) and d.strip())
            else:
                text = ''
        else:
            text = self._annot_input.toPlainText().strip()
        if not text:
            self._status_lbl.setText('⚠ 텍스트를 가져올 수 없습니다.')
            return
        style = _ANNOT_MAP.get(self._annot_style_cb.currentText(), 'explain')
        from utils.ollama_client import generate_annotation
        self._start_worker(generate_annotation, text, model, style, status='어노테이션 생성 중…')

    def _on_ollama_ocr_done(self, pages_text: dict[int, str]):
        self._set_busy(False)
        if not pages_text:
            self._output.clear()
            self._status_lbl.setText('⚠ OCR 결과가 없습니다.')
            return
        full = '\n\n'.join(
            f'── 페이지 {i + 1} ──\n{pages_text[i]}'
            for i in sorted(pages_text)
        )
        self._output.setPlainText(full)
        chars = sum(len(t) for t in pages_text.values())
        self._status_lbl.setText(f'✅ OCR 완료 — {chars:,}자')

    # ── 완료 핸들러 ───────────────────────────────────────────────────

    def _on_done(self, text: str):
        self._set_busy(False)
        self._output.setPlainText(text)
        self._status_lbl.setText(f'✅ 완료 — {len(text):,}자')

    def _on_qa_done(self, question: str, answer: str):
        self._set_busy(False)
        self._qa_history.append({'role': 'user',      'content': question})
        self._qa_history.append({'role': 'assistant', 'content': answer})
        self._qa_input.clear()
        self._qa_display.setHtml(_chat_html(self._qa_history))
        sb = self._qa_display.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._output.setPlainText(answer)
        self._status_lbl.setText('✅ 답변 완료')

    def _on_chat_done(self, question: str, answer: str):
        self._set_busy(False)
        self._chat_history.append({'role': 'user',      'content': question})
        self._chat_history.append({'role': 'assistant', 'content': answer})
        self._chat_input.clear()
        self._chat_display.setHtml(_chat_html(self._chat_history))
        sb = self._chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._output.setPlainText(answer)
        self._status_lbl.setText('✅ 답변 완료')

    def _on_error(self, err: str):
        self._set_busy(False)
        self._status_lbl.setText(f'⚠ {err}')
        self._status_lbl.setStyleSheet(
            'color:#d63060; font-size:12px; background:transparent;')

    def _clear_chat(self):
        self._chat_history.clear()
        self._chat_display.setHtml(_chat_html(
            [], 'Ollama와 자유롭게 대화할 수 있습니다.\nPDF와 무관한 일반 질문도 가능합니다.'))
        self._chat_input.clear()
        self._status_lbl.setText('대화 내역 초기화됨')

    def _clear_qa(self):
        self._qa_history.clear()
        self._qa_context = ''
        self._qa_display.setHtml(_chat_html([], '질문하면 여기에 대화가 쌓입니다.'))
        self._qa_input.clear()
        self._output.clear()
        self._status_lbl.setText('대화 내역 초기화됨')

    # ── 헬퍼 ─────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._progress.setVisible(busy)
        self._status_lbl.setStyleSheet(
            'color:#4361ee; font-size:12px; background:transparent;')
        has_model = bool(self._get_model())
        self._run_btn.setEnabled(not busy and has_model)
        self._qa_ask_btn.setEnabled(not busy and has_model)
        self._chat_ask_btn.setEnabled(not busy and has_model)
        self._refresh_btn.setEnabled(not busy)

    # ── 외부 인터페이스 ───────────────────────────────────────────────

    def set_correction_text(self, text: str, mode: str = 'OCR 오류 보정') -> None:
        self._tabs.setCurrentIndex(3)
        if mode in _CORRECT_TYPES:
            self._correct_type_cb.setCurrentText(mode)
        self._correct_input.setPlainText(text)
        self.show()
        self.raise_()
        self.activateWindow()
