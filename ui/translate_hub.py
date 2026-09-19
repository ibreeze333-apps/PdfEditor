# ui/translate_hub.py — 번역 허브 창
"""Ollama(로컬)·외부 API(ChatGPT/Claude/커스텀)·웹 AI를 한곳에 모은 번역 창.

원문 소스: 📄 페이지 번역 (열린 PDF에서 추출, 스캔본은 OCR) / ✏ 직접 입력
번역 엔진 탭:
  🦙 Ollama — 로컬 모델 (기존 ollama_worker 재사용)
  🔑 API    — 사용자 키로 ChatGPT/Claude/OpenAI호환 서비스 호출
  🌐 웹 AI  — 텍스트+프롬프트를 클립보드에 복사하고 브라우저 열기
              (구독 중인 ChatGPT/Claude 웹을 그대로 활용;
               QtWebEngine 이 설치돼 있으면 내장 창으로도 열 수 있음)
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QSpinBox,
    QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from utils.settings import AppSettings
from utils.translate_text_utils import LANG_PAIRS

# 웹 AI 서비스 프리셋 — 사용자 지정 주소는 별도 입력란
_WEB_SERVICES: dict[str, str] = {
    'ChatGPT': 'https://chatgpt.com/',
    'Claude': 'https://claude.ai/new',
    'Gemini': 'https://gemini.google.com/',
    'DeepL': 'https://www.deepl.com/translator',
    'Google 번역': 'https://translate.google.com/',
    'Papago': 'https://papago.naver.com/',
}

_WEB_PROMPT = (
    '아래 텍스트를 {tgt}로 번역해 주세요. 번역문만 출력하세요.\n'
    '────────────\n{text}'
)


def _webengine_available() -> bool:
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
        return True
    except Exception:
        return False


class TranslateHubWindow(QWidget):
    """싱글톤 플로팅 번역 허브 창 (main_window 가 관리)."""

    def __init__(self, settings: AppSettings,
                 page_callbacks: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window)
        self.setWindowTitle('번역 허브')
        self.setMinimumSize(860, 640)
        self._settings = settings
        self._page_callbacks = page_callbacks
        self._pool = QThreadPool.globalInstance()
        self._busy = False
        self._web_view_win = None   # 내장 웹뷰 창 (QtWebEngine 있을 때)
        self._build_ui()
        self._refresh_ollama_models()
        self._reload_providers()

    # ══════════════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════════════
    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── 상단: 언어 방향 ─────────────────────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel('번역 방향:'))
        self._lang_cb = QComboBox()
        self._lang_cb.addItems(LANG_PAIRS.keys())
        saved_lang = getattr(self._settings, 'translate_lang', '')
        if saved_lang in LANG_PAIRS:
            self._lang_cb.setCurrentText(saved_lang)
        top.addWidget(self._lang_cb)
        top.addStretch(1)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(split, stretch=1)

        # ── 원문 소스 탭 ────────────────────────────────────────────
        self._src_tabs = QTabWidget()
        self._src_tabs.addTab(self._build_page_tab(), '📄 페이지 번역')
        self._src_tabs.addTab(self._build_text_tab(), '✏ 직접 입력')
        split.addWidget(self._src_tabs)

        # ── 엔진 탭 + 결과 ──────────────────────────────────────────
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)

        self._engine_tabs = QTabWidget()
        self._engine_tabs.addTab(self._build_ollama_tab(), '🦙 Ollama (로컬)')
        self._engine_tabs.addTab(self._build_api_tab(),    '🔑 API (ChatGPT·Claude·커스텀)')
        self._engine_tabs.addTab(self._build_web_tab(),    '🌐 웹 AI (구독 활용)')
        bv.addWidget(self._engine_tabs)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        bv.addWidget(self._progress)

        self._status = QLabel(' ')
        self._status.setWordWrap(True)
        bv.addWidget(self._status)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel('번역 결과'))
        out_row.addStretch(1)
        copy_btn = QPushButton('📋 결과 복사')
        copy_btn.clicked.connect(self._copy_output)
        out_row.addWidget(copy_btn)
        bv.addLayout(out_row)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText('번역 결과가 여기에 표시됩니다.')
        bv.addWidget(self._output, stretch=1)

        split.addWidget(bottom)
        split.setSizes([220, 420])

    def _build_page_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self._radio_current = QRadioButton('현재 페이지')
        self._radio_range   = QRadioButton('범위')
        self._radio_all     = QRadioButton('전체')
        self._radio_current.setChecked(True)
        grp = QButtonGroup(w)
        for r in (self._radio_current, self._radio_range, self._radio_all):
            grp.addButton(r)
            row.addWidget(r)
        self._from_spin = QSpinBox(); self._from_spin.setMinimum(1); self._from_spin.setMaximum(9999)
        self._to_spin   = QSpinBox(); self._to_spin.setMinimum(1);   self._to_spin.setMaximum(9999)
        row.addWidget(self._from_spin)
        row.addWidget(QLabel('~'))
        row.addWidget(self._to_spin)
        row.addStretch(1)
        v.addLayout(row)
        tip = QLabel('열려 있는 PDF에서 텍스트를 추출해 번역합니다. '
                     '스캔본은 자동으로 OCR 후 번역합니다.')
        tip.setStyleSheet('color:#6b7280;')
        tip.setWordWrap(True)
        v.addWidget(tip)
        v.addStretch(1)
        return w

    def _build_text_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._input = QTextEdit()
        self._input.setPlaceholderText('번역할 텍스트를 붙여넣으세요.')
        v.addWidget(self._input)
        return w

    # ── 엔진: Ollama ────────────────────────────────────────────────
    def _build_ollama_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel('모델:'))
        self._ollama_model_cb = QComboBox()
        self._ollama_model_cb.setMinimumWidth(200)
        row.addWidget(self._ollama_model_cb, stretch=1)
        self._ollama_refresh_btn = QPushButton('🔄')
        self._ollama_refresh_btn.setFixedWidth(30)
        self._ollama_refresh_btn.setToolTip('Ollama 모델 목록 새로고침')
        self._ollama_refresh_btn.clicked.connect(self._refresh_ollama_models)
        row.addWidget(self._ollama_refresh_btn)
        self._ollama_run_btn = QPushButton('▶ 번역')
        self._ollama_run_btn.clicked.connect(self._run_ollama)
        row.addWidget(self._ollama_run_btn)
        v.addLayout(row)
        self._ollama_status = QLabel(' ')
        self._ollama_status.setStyleSheet('color:#6b7280;')
        v.addWidget(self._ollama_status)
        v.addStretch(1)
        return w

    # ── 엔진: API ───────────────────────────────────────────────────
    def _build_api_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel('제공자:'))
        self._provider_cb = QComboBox()
        self._provider_cb.setMinimumWidth(220)
        row.addWidget(self._provider_cb, stretch=1)
        manage_btn = QPushButton('⚙ 제공자 관리')
        manage_btn.setToolTip('API 키·주소·모델 추가/수정 (키는 사용자가 직접 입력)')
        manage_btn.clicked.connect(self._open_provider_dialog)
        row.addWidget(manage_btn)
        self._api_run_btn = QPushButton('▶ 번역')
        self._api_run_btn.clicked.connect(self._run_api)
        row.addWidget(self._api_run_btn)
        v.addLayout(row)
        self._api_status = QLabel(' ')
        self._api_status.setStyleSheet('color:#6b7280;')
        self._api_status.setWordWrap(True)
        v.addWidget(self._api_status)
        v.addStretch(1)
        return w

    # ── 엔진: 웹 AI ─────────────────────────────────────────────────
    def _build_web_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel('서비스:'))
        self._web_cb = QComboBox()
        self._web_cb.addItems(_WEB_SERVICES.keys())
        self._web_cb.addItem('직접 입력…')
        saved = getattr(self._settings, 'hub_web_service', '')
        if saved and self._web_cb.findText(saved) >= 0:
            self._web_cb.setCurrentText(saved)
        self._web_cb.currentTextChanged.connect(self._on_web_service_changed)
        row.addWidget(self._web_cb)
        self._web_url_ed = QLineEdit()
        self._web_url_ed.setPlaceholderText('https:// 주소 직접 입력')
        self._web_url_ed.setText(getattr(self._settings, 'hub_custom_web_url', ''))
        self._web_url_ed.setVisible(self._web_cb.currentText() == '직접 입력…')
        row.addWidget(self._web_url_ed, stretch=1)
        row.addStretch(1)
        v.addLayout(row)

        btn_row = QHBoxLayout()
        open_btn = QPushButton('📋 복사 후 브라우저 열기')
        open_btn.setToolTip('번역 프롬프트+원문을 클립보드에 복사하고 브라우저에서 서비스를 엽니다.\n'
                            '로그인된 구독 계정을 그대로 사용할 수 있습니다.')
        open_btn.clicked.connect(lambda: self._open_web(embedded=False))
        btn_row.addWidget(open_btn)
        self._embed_btn = QPushButton('🪟 내장 창으로 열기')
        self._embed_btn.setToolTip('앱 안의 웹뷰 창에서 엽니다 (QtWebEngine 필요)')
        self._embed_btn.clicked.connect(lambda: self._open_web(embedded=True))
        self._embed_btn.setEnabled(_webengine_available())
        if not _webengine_available():
            self._embed_btn.setToolTip('QtWebEngine 미설치 — 기본 브라우저 열기를 사용하세요')
        btn_row.addWidget(self._embed_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        tip = QLabel(
            '💡 붙여넣기(Ctrl+V)만 하면 됩니다. 구독 중인 ChatGPT/Claude 웹 계정의 '
            '고성능 모델을 추가 비용 없이 활용하는 방법입니다.\n'
            '외부 브라우저 방식이 로그인 유지·봇 차단 회피에 가장 안정적입니다.')
        tip.setStyleSheet('color:#6b7280;')
        tip.setWordWrap(True)
        v.addWidget(tip)
        v.addStretch(1)
        return w

    # ══════════════════════════════════════════════════════════════════
    # 원문 수집
    # ══════════════════════════════════════════════════════════════════
    def _selected_pages(self) -> list[int]:
        if self._page_callbacks is None or not self._page_callbacks['is_open']():
            return []
        n = self._page_callbacks['page_count']()
        if n <= 0:
            return []
        self._from_spin.setMaximum(n)
        self._to_spin.setMaximum(n)
        if self._radio_current.isChecked():
            return [self._page_callbacks['current_page']()]
        if self._radio_all.isChecked():
            return list(range(n))
        a = max(1, min(self._from_spin.value(), n))
        b = max(a, min(self._to_spin.value(), n))
        return list(range(a - 1, b))

    def _collect_pages_data(self):
        """페이지 탭: [(idx, str|ndarray)] 또는 None."""
        if self._page_callbacks is None or not self._page_callbacks['is_open']():
            self._status.setText('⚠ PDF가 열려 있지 않습니다.')
            return None
        pages = self._selected_pages()
        if not pages:
            self._status.setText('⚠ 번역할 페이지가 없습니다.')
            return None
        self._status.setText('페이지 데이터 준비 중…')
        data = self._page_callbacks['get_page_data'](pages)
        if not data:
            self._status.setText('⚠ 페이지 데이터를 가져오지 못했습니다.')
            return None
        return data

    def _current_text(self) -> str:
        """직접 입력 탭 텍스트 (웹 AI 는 페이지 탭이면 텍스트 부분만)."""
        if self._src_tabs.currentIndex() == 1:
            return self._input.toPlainText().strip()
        data = self._collect_pages_data()
        if not data:
            return ''
        parts = [d for _, d in data if isinstance(d, str) and d.strip()]
        return '\n\n'.join(parts)

    def _lang_pair(self) -> tuple[str, str]:
        return LANG_PAIRS[self._lang_cb.currentText()]

    # ══════════════════════════════════════════════════════════════════
    # Ollama 실행
    # ══════════════════════════════════════════════════════════════════
    def _refresh_ollama_models(self):
        from utils.ollama_client import is_running, get_text_models
        self._ollama_model_cb.clear()
        if not is_running():
            self._ollama_run_btn.setEnabled(False)
            self._ollama_status.setText(
                '⚪ Ollama 미실행 — 터미널에서 ollama serve 를 실행하세요')
            return
        models = get_text_models()
        if not models:
            self._ollama_run_btn.setEnabled(False)
            self._ollama_status.setText('🟡 Ollama 실행 중 — 설치된 모델이 없습니다')
            return
        self._ollama_model_cb.addItems(models)
        saved = getattr(self._settings, 'hub_ollama_model', '')
        if saved and self._ollama_model_cb.findText(saved) >= 0:
            self._ollama_model_cb.setCurrentText(saved)
        self._ollama_run_btn.setEnabled(True)
        self._ollama_status.setText(f'🟢 Ollama 연결됨 — {len(models)}개 모델')

    def _run_ollama(self):
        if self._busy:
            return
        model = self._ollama_model_cb.currentText()
        if not model or model.startswith('──'):
            self._status.setText('⚠ Ollama 모델을 선택하세요.')
            return
        src, tgt = self._lang_pair()
        self._settings.hub_ollama_model = model
        self._settings.translate_lang = self._lang_cb.currentText()
        self._settings.save()

        from workers.ollama_worker import (
            OllamaTranslateWorker, OllamaPageTranslateWorker)
        if self._src_tabs.currentIndex() == 1:
            text = self._input.toPlainText().strip()
            if not text:
                self._status.setText('⚠ 번역할 텍스트를 입력하세요.')
                return
            worker = OllamaTranslateWorker(text, src, tgt, model)
        else:
            data = self._collect_pages_data()
            if not data:
                return
            worker = OllamaPageTranslateWorker(data, src, tgt, model)
        self._start_worker(worker)

    # ══════════════════════════════════════════════════════════════════
    # API 실행
    # ══════════════════════════════════════════════════════════════════
    def _reload_providers(self):
        self._provider_cb.clear()
        for p in self._settings.ai_providers:
            has_key = '🔑 ' if (p.get('api_key') or '').strip() else '· '
            self._provider_cb.addItem(has_key + p.get('name', '?'), p.get('name', ''))
        active = getattr(self._settings, 'ai_provider_active', '')
        idx = self._provider_cb.findData(active)
        if idx >= 0:
            self._provider_cb.setCurrentIndex(idx)
        self._update_api_status()

    def _current_provider(self) -> dict | None:
        name = self._provider_cb.currentData()
        for p in self._settings.ai_providers:
            if p.get('name') == name:
                return p
        return None

    def _update_api_status(self):
        p = self._current_provider()
        if p is None:
            self._api_status.setText('제공자를 추가하세요 (⚙ 제공자 관리).')
            return
        if not (p.get('api_key') or '').strip():
            self._api_status.setText(
                f"⚠ '{p.get('name')}' 의 API 키가 없습니다 — ⚙ 제공자 관리에서 입력하세요.")
        else:
            self._api_status.setText(
                f"모델: {p.get('model', '?')}  ·  {p.get('base_url', '')}")

    def _open_provider_dialog(self):
        from ui.dialogs.ai_provider_dialog import AiProviderDialog
        dlg = AiProviderDialog(self._settings.ai_providers, self)
        if dlg.exec():
            self._settings.ai_providers = dlg.providers()
            self._settings.save()
            self._reload_providers()

    def _run_api(self):
        if self._busy:
            return
        provider = self._current_provider()
        if provider is None:
            self._status.setText('⚠ 제공자를 먼저 추가하세요.')
            return
        if not (provider.get('api_key') or '').strip():
            self._status.setText(
                f"⚠ '{provider.get('name')}' 의 API 키가 없습니다 — ⚙ 제공자 관리에서 입력하세요.")
            return
        src, tgt = self._lang_pair()
        self._settings.ai_provider_active = provider.get('name', '')
        self._settings.translate_lang = self._lang_cb.currentText()
        self._settings.save()

        from workers.api_translate_worker import (
            ApiTranslateWorker, ApiPageTranslateWorker)
        if self._src_tabs.currentIndex() == 1:
            text = self._input.toPlainText().strip()
            if not text:
                self._status.setText('⚠ 번역할 텍스트를 입력하세요.')
                return
            worker = ApiTranslateWorker(dict(provider), text, src, tgt)
        else:
            data = self._collect_pages_data()
            if not data:
                return
            worker = ApiPageTranslateWorker(dict(provider), data, src, tgt)
        self._start_worker(worker)

    # ══════════════════════════════════════════════════════════════════
    # 웹 AI 실행
    # ══════════════════════════════════════════════════════════════════
    def _on_web_service_changed(self, text: str):
        self._web_url_ed.setVisible(text == '직접 입력…')

    def _web_url(self) -> str:
        name = self._web_cb.currentText()
        if name == '직접 입력…':
            url = self._web_url_ed.text().strip()
            if url and not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            return url
        return _WEB_SERVICES.get(name, '')

    def _open_web(self, embedded: bool):
        url = self._web_url()
        if not url:
            self._status.setText('⚠ 주소를 입력하세요.')
            return
        text = self._current_text()
        if text:
            _, tgt = self._lang_pair()
            tgt_name = {'ko': '한국어', 'en': '영어', 'ja': '일본어',
                        'zh': '중국어'}.get(tgt, tgt)
            name = self._web_cb.currentText()
            if name in ('DeepL', 'Google 번역', 'Papago'):
                clip = text          # 전용 번역기는 원문만
            else:
                clip = _WEB_PROMPT.format(tgt=tgt_name, text=text)
            QApplication.clipboard().setText(clip)
            copied = f'📋 {len(text):,}자 복사됨 — '
        else:
            copied = ''

        # 설정 저장
        self._settings.hub_web_service = self._web_cb.currentText()
        if self._web_cb.currentText() == '직접 입력…':
            self._settings.hub_custom_web_url = self._web_url_ed.text().strip()
        self._settings.save()

        if embedded and _webengine_available():
            self._open_embedded_view(url)
            self._status.setText(f'{copied}내장 창에서 열림. 붙여넣기(Ctrl+V) 하세요.')
        else:
            webbrowser.open(url)
            self._status.setText(f'{copied}브라우저에서 열림. 붙여넣기(Ctrl+V) 하세요.')

    def _open_embedded_view(self, url: str):
        """QtWebEngine 내장 웹뷰 창 (설치된 경우에만)."""
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        if self._web_view_win is None:
            win = QWidget()
            win.setWindowFlag(Qt.WindowType.Window)
            win.setWindowTitle('웹 AI 번역')
            win.setMinimumSize(900, 700)
            v = QVBoxLayout(win)
            v.setContentsMargins(0, 0, 0, 0)
            bar = QHBoxLayout()
            bar.setContentsMargins(6, 4, 6, 4)
            url_ed = QLineEdit()
            url_ed.setReadOnly(True)
            bar.addWidget(url_ed, stretch=1)
            ext_btn = QPushButton('기본 브라우저로')
            bar.addWidget(ext_btn)
            v.addLayout(bar)
            view = QWebEngineView()
            v.addWidget(view, stretch=1)
            view.urlChanged.connect(lambda u: url_ed.setText(u.toString()))
            ext_btn.clicked.connect(lambda: webbrowser.open(url_ed.text()))
            win._view = view          # 참조 유지
            self._web_view_win = win
        self._web_view_win._view.load(QUrl(url))
        self._web_view_win.show()
        self._web_view_win.raise_()
        self._web_view_win.activateWindow()

    # ══════════════════════════════════════════════════════════════════
    # 워커 공통
    # ══════════════════════════════════════════════════════════════════
    def _start_worker(self, worker):
        self._set_busy(True)
        self._output.clear()
        worker.signals.status.connect(self._status.setText)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        self._pool.start(worker)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._ollama_run_btn.setEnabled(not busy)
        self._api_run_btn.setEnabled(not busy)
        if not busy:
            self._progress.setValue(0)

    def _on_progress(self, done: int, total: int):
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(done)

    def _on_done(self, text: str):
        self._set_busy(False)
        self._output.setPlainText(text)
        self._status.setText(f'✅ 번역 완료 — {len(text):,}자')
        # Ollama 버튼은 연결 상태에 따라 복원
        self._refresh_ollama_models()

    def _on_error(self, msg: str):
        self._set_busy(False)
        self._status.setText(f'⚠ {msg[:300]}')
        self._refresh_ollama_models()

    def _copy_output(self):
        text = self._output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._status.setText(f'📋 결과 {len(text):,}자 복사됨')
