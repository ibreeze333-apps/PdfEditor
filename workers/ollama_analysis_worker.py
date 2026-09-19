# workers/ollama_analysis_worker.py — Ollama 분석 범용 백그라운드 워커
from __future__ import annotations
import logging
from PySide6.QtCore import QRunnable, QObject, Signal

logger = logging.getLogger(__name__)


class OllamaAnalysisSignals(QObject):
    progress = Signal(int, int)
    status   = Signal(str)
    finished = Signal(str)
    error    = Signal(str)


class OllamaAnalysisWorker(QRunnable):
    """fn(*args, **kwargs) 를 백그라운드에서 실행하는 범용 분석 워커."""

    def __init__(self, fn, *args, status_msg: str = 'Ollama 처리 중…', **kwargs):
        super().__init__()
        self.signals     = OllamaAnalysisSignals()
        self._fn         = fn
        self._args       = args
        self._kwargs     = kwargs
        self._status_msg = status_msg
        self.setAutoDelete(True)

    def run(self):
        try:
            self.signals.status.emit(self._status_msg)
            result = self._fn(*self._args, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            logger.exception('OllamaAnalysisWorker 실패')
            self.signals.error.emit(str(e))
