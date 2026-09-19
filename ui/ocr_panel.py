# ui/ocr_panel.py - OCR QDockWidget
from __future__ import annotations
import webbrowser
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QComboBox,
    QProgressBar, QCheckBox, QSpinBox, QApplication,
    QFrame, QMessageBox,
)
from utils.settings import AppSettings
# numpy/pytesseract 등 무거운 모듈은 _run() 안에서 lazy import
# (최상위 import 시 numpy import lock → 창 열릴 때 UI 블로킹 방지)

_TESSERACT_DOWNLOAD_URL = (
    'https://github.com/UB-Mannheim/tesseract/wiki'
)


_LANG_MAP = {
    '한국어+영어': {'settings': 'ko+en', 'tesseract': 'kor+eng'},
    '영어만':      {'settings': 'en',    'tesseract': 'eng'},
    '일본어+영어': {'settings': 'ja+en', 'tesseract': 'jpn+eng'},
    '중국어(간체)+영어': {'settings': 'zh+en', 'tesseract': 'chi_sim+eng'},
}

_ENGINE_MAP = {
    '⚡ 빠른 추출 (텍스트 PDF)': 'fast',
    '⚡ 빠른 추출 (스캔된 PDF)': 'tesseract',
}


class OcrPanel(QDockWidget):
    def __init__(self, doc, canvas, settings: AppSettings, parent=None):
        super().__init__('OCR 텍스트 추출', parent)
        self._doc = doc
        self._canvas = canvas
        self._settings = settings
        self._pool = QThreadPool.globalInstance()
        self._workers_done = 0
        self._workers_total = 0
        self._pages_text: dict[int, str] = {}

        w = QWidget()
        lay = QVBoxLayout(w)

        eng_row = QHBoxLayout()
        eng_row.addWidget(QLabel('엔진:'))
        self._engine_cb = QComboBox()
        self._engine_cb.addItems(list(_ENGINE_MAP.keys()))
        engine_tip = (
            '빠른 추출 (텍스트 PDF): PDF에 텍스트가 내장된 경우 즉시 추출\n'
            '빠른 추출 (스캔된 PDF): Tesseract 기반의 가벼운 스캔본 OCR\n'
        )
        self._engine_cb.setToolTip(engine_tip)
        self._engine_cb.currentTextChanged.connect(self._on_engine_changed)
        eng_row.addWidget(self._engine_cb)
        eng_row.addStretch()
        lay.addLayout(eng_row)


        opt = QHBoxLayout()
        opt.addWidget(QLabel('언어:'))
        self._lang_cb = QComboBox()
        self._lang_cb.addItems(list(_LANG_MAP.keys()))
        self._lang_cb.currentTextChanged.connect(lambda _: self._save_settings())
        opt.addWidget(self._lang_cb)
        opt.addStretch()
        lay.addLayout(opt)

        rng = QHBoxLayout()
        rng.addWidget(QLabel('페이지:'))
        self._page_from = QSpinBox(); self._page_from.setMinimum(1)
        self._page_to = QSpinBox(); self._page_to.setMinimum(1)
        self._page_from.setEnabled(False)
        self._page_to.setEnabled(False)
        rng.addWidget(self._page_from)
        rng.addWidget(QLabel('~'))
        rng.addWidget(self._page_to)
        self._cur_only = QCheckBox('현재 페이지만')
        self._cur_only.setChecked(True)
        self._cur_only.toggled.connect(self._on_cur_only_toggled)
        rng.addWidget(self._cur_only)
        rng.addStretch()
        lay.addLayout(rng)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton('▶ OCR 시작')
        self._run_btn.clicked.connect(self._run)
        self._copy_btn = QPushButton('📋 복사')
        self._copy_btn.clicked.connect(self._copy)
        self._clear_btn = QPushButton('🗑 지우기')
        self._clear_btn.clicked.connect(lambda: self._result.clear())
        self._online_ocr_btn = QPushButton('🌐 온라인 OCR')
        self._online_ocr_btn.setToolTip(
            '현재 페이지를 이미지로 클립보드에 복사하고\n'
            'Google 번역 이미지 모드를 브라우저로 엽니다.\n'
            '브라우저에서 Ctrl+V 로 붙여넣기 하세요.'
        )
        self._online_ocr_btn.clicked.connect(self._open_online_ocr)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._online_ocr_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # ── Tesseract 미설치 배너 ──────────────────────────────────────
        self._tess_banner = self._build_tess_banner()
        lay.addWidget(self._tess_banner)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status = QLabel('준비')
        lay.addWidget(self._status)
        self._result = QTextEdit()
        self._result.setReadOnly(False)
        lay.addWidget(self._result)

        self.setWidget(w)
        self.setMinimumWidth(300)
        self._load_settings()
        # 생성 시 Java 검사 없이 UI만 동기화 (Java 검사는 ▶ OCR 시작 때 수행)
        self._sync_engine_ui(self._engine_cb.currentText())
        self._refresh_tess_banner()

    def _sync_engine_ui(self, text: str):
        """엔진 콤보 변경 시 UI 상태만 업데이트 (Java 검사 없음)."""
        engine = _ENGINE_MAP.get(text, 'fast')
        self._lang_cb.setEnabled(engine == 'tesseract')
        # Tesseract 배너는 엔진 변경 때마다 갱신
        if hasattr(self, '_tess_banner'):
            self._refresh_tess_banner()

    def _on_engine_changed(self, text: str):
        self._sync_engine_ui(text)
        self._save_settings()

    def _load_settings(self):
        for cb in (self._engine_cb, self._lang_cb):
            cb.blockSignals(True)
        try:
            engine_label = next(
                (label for label, engine in _ENGINE_MAP.items() if engine == self._settings.ocr_engine),
                next(iter(_ENGINE_MAP)),
            )
            self._engine_cb.setCurrentText(engine_label)
            lang_label = next(
                (label for label, cfg in _LANG_MAP.items() if cfg['settings'] == self._settings.ocr_lang),
                next(iter(_LANG_MAP)),
            )
            self._lang_cb.setCurrentText(lang_label)
        finally:
            for cb in (self._engine_cb, self._lang_cb):
                cb.blockSignals(False)

    def _save_settings(self):
        self._settings.ocr_engine = self._current_engine()
        lang_cfg = _LANG_MAP.get(self._lang_cb.currentText(), next(iter(_LANG_MAP.values())))
        self._settings.ocr_lang  = lang_cfg['settings']
        self._settings.save()

    def _current_engine(self) -> str:
        return _ENGINE_MAP.get(self._engine_cb.currentText(), 'fast')

    def _on_cur_only_toggled(self, checked: bool):
        self._page_from.setEnabled(not checked)
        self._page_to.setEnabled(not checked)
        if not checked and self._doc.is_open:
            n = self._doc.page_count()
            self._page_from.setMaximum(n)
            self._page_to.setMaximum(n)
            self._page_from.setValue(1)
            self._page_to.setValue(n)

    def _run(self):
        if not self._doc.is_open:
            return
        self._save_settings()
        n = self._doc.page_count()
        self._page_from.setMaximum(n)
        self._page_to.setMaximum(n)

        if self._cur_only.isChecked():
            pages = [self._canvas.current_page()]
        else:
            pages = list(range(self._page_from.value() - 1, self._page_to.value()))

        engine = self._current_engine()

        if engine == 'fast':
            self._result.clear()
            self._status.setText('텍스트 추출 중…')
            from utils.fitz_qt_bridge import extract_page_text
            pages_text: dict[int, str] = {}
            for idx in pages:
                page = self._doc.fitz_page(idx)
                text = extract_page_text(page)
                pages_text[idx] = text if text else '(내장 텍스트 없음 - 스캔된 PDF는 Tesseract를 사용하세요)'
            self._pages_text = pages_text
            full = '\n\n'.join(f'── 페이지 {i + 1} ──\n{pages_text[i]}' for i in sorted(pages_text))
            self._result.setPlainText(full)
            chars = sum(len(t) for t in pages_text.values())
            self._status.setText(f'완료 - {chars:,}자')
            return

        self._result.clear()
        self._run_btn.setEnabled(False)

        # 실제 OCR 실행 직전에 heavy import (numpy 등) — UI 블로킹 방지
        from workers.ocr_worker import OcrWorker, qimage_to_np
        from utils.fitz_qt_bridge import render_page

        # Tesseract
        # ── 페이지 렌더링은 메인 스레드에서 수행 (fitz는 스레드-비안전) ──
        lang_cfg = _LANG_MAP.get(self._lang_cb.currentText(), next(iter(_LANG_MAP.values())))
        lang = lang_cfg.get('tesseract', 'kor+eng')

        page_arrays: list[tuple[int, object]] = []   # (page_idx, np.ndarray)
        render_errors: list[tuple[int, str]] = []
        self._status.setText('페이지 렌더링 중…')
        for idx in pages:
            try:
                fitz_page = self._doc.fitz_page(idx)
                img = render_page(fitz_page, zoom=2.0)
                page_arrays.append((idx, qimage_to_np(img)))
            except Exception as e:
                import traceback
                render_errors.append((idx, traceback.format_exc()))

        if not page_arrays and render_errors:
            self._progress.setVisible(False)
            self._run_btn.setEnabled(True)
            self._status.setText(f'⚠ 렌더링 실패: {render_errors[0][1][:120]}')
            return

        self._workers_done = 0
        self._workers_total = len(page_arrays)
        self._progress.setMaximum(self._workers_total)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._pages_text = {}
        self._status.setText('OCR 진행 중…')

        for idx, arr in page_arrays:
            worker = OcrWorker(arr, idx, engine='tesseract', lang=lang)
            worker.signals.finished.connect(self._on_page_done)
            worker.signals.progress.connect(lambda _, msg: self._status.setText(msg))
            worker.signals.error.connect(self._on_page_error)
            self._pool.start(worker)

    def _on_odl_done(self, pages_text: dict):
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)
        self._pages_text = pages_text
        full = '\n\n'.join(
            f'── 페이지 {i + 1} ──\n{pages_text[i]}'
            for i in sorted(pages_text)
        )
        self._result.setPlainText(full)
        chars = sum(len(t) for t in pages_text.values())
        self._status.setText(f'완료 - {chars:,}자')


    def _on_page_error(self, page_idx: int, err: str):
        self._workers_done += 1
        self._progress.setValue(self._workers_done)
        self._status.setText(f'⚠ 페이지 {page_idx + 1} 오류')
        self._result.setPlainText(f'[페이지 {page_idx + 1} 오류]\n{err}')
        if self._workers_done >= self._workers_total:
            self._progress.setVisible(False)
            self._run_btn.setEnabled(True)

    def _on_page_done(self, page_idx: int, text: str):
        self._pages_text[page_idx] = text
        self._workers_done += 1
        self._progress.setValue(self._workers_done)
        if self._workers_done >= self._workers_total:
            full = '\n\n'.join(
                f'── 페이지 {i + 1} ──\n{self._pages_text[i]}'
                for i in sorted(self._pages_text)
            )
            self._result.setPlainText(full)
            self._progress.setVisible(False)
            self._run_btn.setEnabled(True)
            chars = sum(len(t) for t in self._pages_text.values())
            self._status.setText(f'완료 - {chars:,}자')

    @property
    def pages_text(self) -> dict:
        return self._pages_text

    def _copy(self):
        text = self._result.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _open_online_ocr(self):
        """현재 페이지를 이미지로 클립보드에 복사하고 Google 번역 이미지 모드를 연다."""
        if not self._doc.is_open:
            self._status.setText('⚠ PDF가 열려 있지 않습니다.')
            return
        try:
            from utils.fitz_qt_bridge import render_page
            fitz_page = self._doc.fitz_page(self._canvas.current_page())
            img = render_page(fitz_page, zoom=2.0)
            QApplication.clipboard().setImage(img)
            # Google 번역 이미지 탭: OCR + 번역 동시 제공
            webbrowser.open('https://translate.google.com/?sl=auto&tl=ko&op=images')
            self._status.setText('📋 페이지 이미지 복사됨 — 브라우저에서 Ctrl+V 하세요')
        except Exception as e:
            self._status.setText(f'⚠ 이미지 준비 실패: {e}')

    # ── Tesseract 설치 안내 배너 ──────────────────────────────────────

    def _build_tess_banner(self) -> QFrame:
        """Tesseract 미설치 시 표시할 안내 배너를 생성한다."""
        banner = QFrame()
        banner.setObjectName('tessBanner')
        banner.setStyleSheet(
            'QFrame#tessBanner { background: #fff7ed; border: 1.5px solid #fb923c;'
            ' border-radius: 8px; }'
            'QLabel { background: transparent; color: #9a3412; }'
        )
        col = QVBoxLayout(banner)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(6)

        info = QLabel(
            '🔍 Tesseract OCR이 설치되어 있지 않습니다.\n'
            '스캔된 PDF를 텍스트로 변환하려면 Tesseract를 설치하세요.'
        )
        info.setWordWrap(True)
        info.setStyleSheet('font-size: 11px; color: #9a3412; background: transparent;')
        col.addWidget(info)

        steps = QLabel(
            '① 아래 버튼을 눌러 다운로드 페이지를 엽니다.\n'
            '② "tesseract-ocr-w64-setup-*.exe" 파일을 내려받아 설치합니다.\n'
            '③ 설치 시 언어 데이터(Korean, Japanese 등) 항목도 체크하세요.\n'
            '④ 설치 완료 후 앱을 재시작하면 자동으로 인식됩니다.'
        )
        steps.setWordWrap(True)
        steps.setStyleSheet('font-size: 11px; color: #7c2d12; background: transparent;')
        col.addWidget(steps)

        btn_row = QHBoxLayout()
        dl_btn = QPushButton('🌐 Tesseract 다운로드 페이지 열기')
        dl_btn.setStyleSheet(
            'QPushButton { background: #fb923c; color: #fff; border: none;'
            ' border-radius: 5px; padding: 5px 12px; font-weight: 700; font-size: 12px; }'
            'QPushButton:hover { background: #ea580c; }'
        )
        dl_btn.clicked.connect(lambda: webbrowser.open(_TESSERACT_DOWNLOAD_URL))
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        col.addLayout(btn_row)

        return banner

    def _refresh_tess_banner(self):
        """현재 엔진이 tesseract이고 실행파일이 없으면 배너를 표시한다."""
        engine = self._current_engine()
        if engine != 'tesseract':
            self._tess_banner.setVisible(False)
            return
        # lazy import — 무거운 모듈 없이 경로만 확인
        from workers.ocr_worker import _resolve_tesseract_cmd
        installed = _resolve_tesseract_cmd() is not None
        self._tess_banner.setVisible(not installed)
