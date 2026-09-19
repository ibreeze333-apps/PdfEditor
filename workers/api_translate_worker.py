# workers/api_translate_worker.py — 외부 AI API 번역 백그라운드 워커
"""ollama_worker 와 동일한 시그널 패턴으로 API 제공자 번역을 수행한다."""
from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable, QObject, Signal

logger = logging.getLogger('pdf_editor')


class ApiTranslateSignals(QObject):
    progress = Signal(int, int)   # (완료, 전체)
    status   = Signal(str)
    finished = Signal(str)        # 번역 결과 전체 텍스트
    error    = Signal(str)


class ApiTranslateWorker(QRunnable):
    """API 제공자로 텍스트를 청크 단위 번역한다 (텍스트 입력 탭용)."""

    def __init__(self, provider: dict, text: str, src: str, tgt: str):
        super().__init__()
        self.signals   = ApiTranslateSignals()
        self._provider = provider
        self._text     = text
        self._src      = src
        self._tgt      = tgt
        self.setAutoDelete(True)

    def run(self):
        try:
            from utils.translate_text_utils import clean_pdf_text, chunk_paragraphs
            from utils.ai_translate import translate_via_provider

            name = self._provider.get('name', 'API')
            self.signals.status.emit('텍스트 전처리 중…')
            cleaned = clean_pdf_text(self._text)
            chunks = chunk_paragraphs(cleaned, max_chars=2000)

            if not chunks:
                self.signals.error.emit('번역할 텍스트가 없습니다.')
                return

            total   = len(chunks)
            results = []
            for i, chunk in enumerate(chunks):
                self.signals.status.emit(f'{name} 번역 중… ({i + 1}/{total})')
                self.signals.progress.emit(i, total)
                try:
                    results.append(
                        translate_via_provider(self._provider, chunk,
                                               self._src, self._tgt))
                except Exception as e:
                    # 키 오류 등은 첫 청크에서 바로 중단하는 편이 낫다
                    if i == 0:
                        raise
                    logger.warning('청크 %d 번역 실패: %s', i, e)
                    results.append(f'[번역 실패: {chunk[:30]}…]')

            self.signals.progress.emit(total, total)
            self.signals.finished.emit('\n\n'.join(results))

        except Exception as e:
            logger.exception('ApiTranslateWorker 실패')
            self.signals.error.emit(str(e))


class ApiPageTranslateWorker(QRunnable):
    """페이지 데이터(텍스트 or 이미지)를 API 제공자로 번역한다 (페이지 탭용)."""

    def __init__(self, provider: dict, pages_data, src: str, tgt: str,
                 ocr_lang: str = 'kor+eng'):
        super().__init__()
        self.signals     = ApiTranslateSignals()
        self._provider   = provider
        self._pages_data = pages_data   # list[(page_idx, str | np.ndarray)]
        self._src        = src
        self._tgt        = tgt
        self._ocr_lang   = ocr_lang
        self.setAutoDelete(True)

    def run(self):
        try:
            from utils.translate_text_utils import (
                clean_pdf_text, clean_ocr_text, chunk_paragraphs)
            from utils.ai_translate import translate_via_provider
            from workers.ocr_worker import _run_tesseract_ocr, _build_paragraphs

            name          = self._provider.get('name', 'API')
            total_pages   = len(self._pages_data)
            cleaned_pages = []

            for step, (page_idx, data) in enumerate(self._pages_data):
                if isinstance(data, str):
                    self.signals.status.emit(
                        f'[{step + 1}/{total_pages}] 페이지 {page_idx + 1} 준비 중…')
                    if data.strip():
                        cleaned_pages.append(clean_pdf_text(data))
                else:
                    self.signals.status.emit(
                        f'[{step + 1}/{total_pages}] 페이지 {page_idx + 1} OCR 중…')
                    items = _run_tesseract_ocr(data, self._ocr_lang, 0.5)
                    raw   = _build_paragraphs(items)
                    if raw.strip():
                        cleaned_pages.append(clean_ocr_text(raw))

            combined = '\n\n'.join(p for p in cleaned_pages if p.strip())
            chunks   = chunk_paragraphs(combined, max_chars=2000)

            if not chunks:
                self.signals.error.emit('번역할 텍스트가 없습니다.')
                return

            total   = len(chunks)
            results = []
            for i, chunk in enumerate(chunks):
                self.signals.status.emit(f'{name} 번역 중… ({i + 1}/{total})')
                self.signals.progress.emit(i, total)
                try:
                    results.append(
                        translate_via_provider(self._provider, chunk,
                                               self._src, self._tgt))
                except Exception as e:
                    if i == 0:
                        raise
                    logger.warning('청크 %d 번역 실패: %s', i, e)
                    results.append(f'[번역 실패: {chunk[:30]}…]')

            self.signals.progress.emit(total, total)
            self.signals.finished.emit('\n\n'.join(results))

        except Exception as e:
            logger.exception('ApiPageTranslateWorker 실패')
            self.signals.error.emit(str(e))
