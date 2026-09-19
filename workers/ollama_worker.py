# workers/ollama_worker.py — Ollama 번역 / Vision OCR 백그라운드 워커
from __future__ import annotations
import logging
from PySide6.QtCore import QRunnable, QObject, Signal

logger = logging.getLogger(__name__)


# ── 시그널 ────────────────────────────────────────────────────────────

class OllamaTranslateSignals(QObject):
    progress = Signal(int, int)   # (완료, 전체)
    status   = Signal(str)
    finished = Signal(str)        # 번역 결과 전체 텍스트
    error    = Signal(str)


class OllamaOcrSignals(QObject):
    progress = Signal(int, int)   # (완료, 전체)
    status   = Signal(str)
    finished = Signal(object)     # dict {page_idx: str} — _on_odl_done 과 동일 형식
    error    = Signal(str)


# ── 번역 워커 ─────────────────────────────────────────────────────────

class OllamaTranslateWorker(QRunnable):
    """Ollama 로컬 모델로 텍스트를 청크 단위 번역한다 (텍스트 입력 탭용)."""

    def __init__(self, text: str, src: str, tgt: str, model: str):
        super().__init__()
        self.signals = OllamaTranslateSignals()
        self._text  = text
        self._src   = src
        self._tgt   = tgt
        self._model = model
        self.setAutoDelete(True)

    def run(self):
        try:
            from utils.translate_text_utils import clean_pdf_text, chunk_paragraphs
            from utils.ollama_client import translate

            self.signals.status.emit('텍스트 전처리 중…')
            cleaned = clean_pdf_text(self._text)
            # Ollama 는 컨텍스트 윈도우가 크므로 청크를 크게 설정
            chunks = chunk_paragraphs(cleaned, max_chars=1500)

            if not chunks:
                self.signals.error.emit('번역할 텍스트가 없습니다.')
                return

            total   = len(chunks)
            results = []

            for i, chunk in enumerate(chunks):
                self.signals.status.emit(f'Ollama 번역 중… ({i + 1}/{total})')
                self.signals.progress.emit(i, total)
                try:
                    results.append(translate(chunk, self._src, self._tgt, self._model))
                except Exception as e:
                    logger.warning('청크 %d 번역 실패: %s', i, e)
                    results.append(f'[번역 실패: {chunk[:30]}…]')

            self.signals.progress.emit(total, total)
            self.signals.finished.emit('\n\n'.join(results))

        except Exception as e:
            logger.exception('OllamaTranslateWorker 실패')
            self.signals.error.emit(str(e))


class OllamaPageTranslateWorker(QRunnable):
    """페이지 데이터(텍스트 or 이미지)를 Ollama로 번역한다 (페이지 번역 탭용)."""

    def __init__(self, pages_data, src: str, tgt: str, model: str,
                 ocr_lang: str = 'kor+eng'):
        super().__init__()
        self.signals     = OllamaTranslateSignals()
        self._pages_data = pages_data   # list[(page_idx, str | np.ndarray)]
        self._src        = src
        self._tgt        = tgt
        self._model      = model
        self._ocr_lang   = ocr_lang
        self.setAutoDelete(True)

    def run(self):
        try:
            from utils.translate_text_utils import clean_pdf_text, clean_ocr_text, chunk_paragraphs
            from utils.ollama_client import translate
            from workers.ocr_worker import _run_tesseract_ocr, _build_paragraphs

            total_pages   = len(self._pages_data)
            cleaned_pages = []

            for step, (page_idx, data) in enumerate(self._pages_data):
                if isinstance(data, str):
                    self.signals.status.emit(
                        f'[{step + 1}/{total_pages}] 페이지 {page_idx + 1} 준비 중…'
                    )
                    if data.strip():
                        cleaned_pages.append(clean_pdf_text(data))
                else:
                    self.signals.status.emit(
                        f'[{step + 1}/{total_pages}] 페이지 {page_idx + 1} OCR 중…'
                    )
                    items = _run_tesseract_ocr(data, self._ocr_lang, 0.5)
                    raw   = _build_paragraphs(items)
                    if raw.strip():
                        cleaned_pages.append(clean_ocr_text(raw))

            combined = '\n\n'.join(p for p in cleaned_pages if p.strip())
            chunks   = chunk_paragraphs(combined, max_chars=1500)

            if not chunks:
                self.signals.error.emit('번역할 텍스트가 없습니다.')
                return

            total   = len(chunks)
            results = []

            for i, chunk in enumerate(chunks):
                self.signals.status.emit(f'Ollama 번역 중… ({i + 1}/{total})')
                self.signals.progress.emit(i, total)
                try:
                    results.append(translate(chunk, self._src, self._tgt, self._model))
                except Exception as e:
                    logger.warning('청크 %d 번역 실패: %s', i, e)
                    results.append(f'[번역 실패: {chunk[:30]}…]')

            self.signals.progress.emit(total, total)
            self.signals.finished.emit('\n\n'.join(results))

        except Exception as e:
            logger.exception('OllamaPageTranslateWorker 실패')
            self.signals.error.emit(str(e))


# ── OCR 워커 ──────────────────────────────────────────────────────────

class OllamaOcrWorker(QRunnable):
    """Ollama Vision 모델로 여러 페이지 이미지를 순서대로 OCR 한다.

    finished 시그널은 dict {page_idx: text} 를 emit — OcrPanel._on_odl_done 과 동일 형식.
    """

    def __init__(self, page_arrays: list[tuple[int, object]],
                 model: str, lang: str = 'ko'):
        """
        Args:
            page_arrays: list[(page_idx, np.ndarray)]
            model:       Ollama vision 모델명
            lang:        OCR 언어 코드 ('ko'|'en'|'ja'|'zh')
        """
        super().__init__()
        self.signals      = OllamaOcrSignals()
        self._page_arrays = page_arrays
        self._model       = model
        self._lang        = lang
        self.setAutoDelete(True)

    def run(self):
        try:
            import io
            from PIL import Image
            from utils.ollama_client import ocr_image_bytes

            total      = len(self._page_arrays)
            pages_text: dict[int, str] = {}

            for i, (page_idx, arr) in enumerate(self._page_arrays):
                self.signals.status.emit(
                    f'Ollama OCR 중… ({i + 1}/{total}) 페이지 {page_idx + 1}'
                )
                self.signals.progress.emit(i, total)
                try:
                    buf = io.BytesIO()
                    Image.fromarray(arr).save(buf, format='PNG')
                    pages_text[page_idx] = ocr_image_bytes(
                        buf.getvalue(), self._model, self._lang
                    )
                except Exception as e:
                    logger.warning('페이지 %d OCR 실패: %s', page_idx, e)
                    pages_text[page_idx] = f'[Ollama OCR 실패: {e}]'

            self.signals.progress.emit(total, total)
            self.signals.finished.emit(pages_text)

        except Exception as e:
            logger.exception('OllamaOcrWorker 실패')
            self.signals.error.emit(str(e))
