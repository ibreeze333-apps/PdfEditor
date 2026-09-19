# workers/ocr_worker.py - OCR async worker
from __future__ import annotations
import os
import sys
from pathlib import Path
import numpy as np
from PySide6.QtCore import QRunnable, QObject, Signal
from PySide6.QtGui import QImage


def _bundle_root() -> Path:
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _patch_pytesseract_windows_subprocess(pytesseract_module):
    if os.name != 'nt':
        return
    subproc = pytesseract_module.pytesseract.subprocess
    startupinfo = None
    creationflags = getattr(subproc, 'CREATE_NO_WINDOW', 0)
    if hasattr(subproc, 'STARTUPINFO'):
        startupinfo = subproc.STARTUPINFO()
        startupinfo.dwFlags |= subproc.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subproc.SW_HIDE

    def _inject_kwargs(kwargs: dict):
        kwargs.setdefault('startupinfo', startupinfo)
        if creationflags:
            kwargs.setdefault('creationflags', creationflags)
        return kwargs

    if not getattr(subproc.run, '_pdf_editor_patched', False):
        original_run = subproc.run
        def _run(*args, **kwargs):
            return original_run(*args, **_inject_kwargs(kwargs))
        _run._pdf_editor_patched = True
        subproc.run = _run

    if not getattr(subproc.check_output, '_pdf_editor_patched', False):
        original_check_output = subproc.check_output
        def _check_output(*args, **kwargs):
            return original_check_output(*args, **_inject_kwargs(kwargs))
        _check_output._pdf_editor_patched = True
        subproc.check_output = _check_output


def _resolve_tesseract_cmd() -> str | None:
    root = _bundle_root()
    candidates = [
        root / 'tesseract' / 'tesseract.exe',
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _resolve_tessdata_dir() -> str | None:
    root = _bundle_root()
    candidates = [
        root / 'tessdata',
        Path(__file__).resolve().parent.parent / 'tessdata',
        root / 'tesseract' / 'tessdata',
        Path(r'C:\Program Files\Tesseract-OCR\tessdata'),
        Path(r'C:\Program Files (x86)\Tesseract-OCR\tessdata'),
    ]
    for candidate in candidates:
        if (candidate / 'eng.traineddata').exists():
            return str(candidate)
    return None


def _build_paragraphs(items: list) -> str:
    if not items:
        return ''

    def _m(bbox):
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        return min(ys), max(ys), min(xs), max(xs)

    entries = []
    for bbox, txt, prob in items:
        t, b, l, r = _m(bbox)
        txt = txt.strip()
        if txt:
            entries.append({
                'top': t, 'bot': b, 'left': l, 'right': r,
                'mid': (t + b) / 2, 'h': b - t, 'text': txt,
            })

    if not entries:
        return ''

    hs = sorted(e['h'] for e in entries)
    s, e_ = max(0, len(hs) // 10), max(1, len(hs) * 9 // 10)
    med_h = hs[(s + e_) // 2] if hs[s:e_] else (hs[len(hs) // 2] if hs else 20)
    char_w = med_h * 0.95
    line_tol = med_h * 0.6

    entries.sort(key=lambda e: e['mid'])
    lines: list[list[dict]] = []
    for entry in entries:
        placed = False
        for line in reversed(lines):
            avg_mid = sum(word['mid'] for word in line) / len(line)
            if abs(entry['mid'] - avg_mid) <= line_tol:
                line.append(entry)
                placed = True
                break
        if not placed:
            lines.append([entry])

    for line in lines:
        line.sort(key=lambda e: e['left'])
    lines.sort(key=lambda line: min(e['top'] for e in line))

    def _join_line(line: list) -> str:
        if not line:
            return ''
        out = [line[0]['text']]
        for prev, curr in zip(line, line[1:]):
            gap = curr['left'] - prev['right']
            out.append('' if gap < char_w * 0.2 else ' ')
            out.append(curr['text'])
        return ''.join(out)

    gaps: list[float] = []
    for prev_line, curr_line in zip(lines, lines[1:]):
        prev_b = max(e['bot'] for e in prev_line)
        curr_t = min(e['top'] for e in curr_line)
        gaps.append(curr_t - prev_b)

    pos_gaps = sorted(g for g in gaps if g > 0)
    if pos_gaps:
        idx65 = max(0, int(len(pos_gaps) * 0.65) - 1)
        normal_gap = pos_gaps[idx65]
        para_thr = max(normal_gap * 2.0, med_h * 1.4)
    else:
        para_thr = med_h * 1.5

    paras: list[list[str]] = [[_join_line(lines[0])]]
    for (_, curr_line), gap in zip(zip(lines, lines[1:]), gaps):
        line_text = _join_line(curr_line)
        if gap > para_thr:
            paras.append([line_text])
        else:
            paras[-1].append(line_text)

    return '\n\n'.join('\n'.join(p) for p in paras)


def _run_tesseract_ocr(arr: np.ndarray, lang: str, conf_threshold: float):
    from PIL import Image
    try:
        import pytesseract
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'Tesseract Python 패키지(pytesseract)가 현재 실행 환경에 설치되어 있지 않습니다.\n'
            '앱은 run.bat 기준으로 Python 3.11을 사용하므로 `py -3.11 -m pip install pytesseract`가 필요합니다.'
        ) from exc

    _patch_pytesseract_windows_subprocess(pytesseract)

    resolved = _resolve_tesseract_cmd()
    if resolved:
        pytesseract.pytesseract.tesseract_cmd = resolved

    tessdata_dir = _resolve_tessdata_dir()
    if tessdata_dir:
        os.environ['TESSDATA_PREFIX'] = tessdata_dir

    try:
        data = pytesseract.image_to_data(
            Image.fromarray(arr),
            lang=lang,
            config='',
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            '시스템에서 tesseract.exe를 찾지 못했습니다.\n'
            'Tesseract OCR 본체를 설치하고 PATH에 추가한 뒤 다시 시도해 주세요.'
        ) from exc

    items = []
    count = len(data.get('text', []))
    for i in range(count):
        txt = (data['text'][i] or '').strip()
        conf_raw = str(data['conf'][i]).strip()
        try:
            conf = float(conf_raw) / 100.0
        except ValueError:
            continue
        if not txt or conf < conf_threshold:
            continue
        left = int(data['left'][i])
        top = int(data['top'][i])
        width = int(data['width'][i])
        height = int(data['height'][i])
        bbox = [
            [left, top], [left + width, top],
            [left + width, top + height], [left, top + height],
        ]
        items.append((bbox, txt, conf))
    return items








def qimage_to_np(img: QImage) -> np.ndarray:
    """QImage → numpy RGB 배열 (메인·워커 스레드 모두에서 호출 가능)."""
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    ptr = img.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, stride))
    arr = arr[:, : w * 3].reshape((h, w, 3))
    return arr.copy()


class OcrSignals(QObject):
    finished = Signal(int, str)
    progress = Signal(int, str)
    error = Signal(int, str)


class OcrWorker(QRunnable):
    """미리 렌더링된 numpy 배열을 받아 Tesseract OCR만 수행한다.

    fitz(PyMuPDF)는 스레드-비안전하므로 페이지 렌더링은 반드시
    호출자(메인 스레드)가 qimage_to_np()로 변환한 뒤 arr로 전달해야 한다.
    """

    def __init__(self, arr: np.ndarray, page_idx: int,
                 engine: str = 'tesseract', lang: str = 'kor+eng',
                 conf_threshold: float = 0.5):
        super().__init__()
        self.signals = OcrSignals()
        self._arr = arr
        self._page_idx = page_idx
        self._engine = engine
        self._lang = lang
        self._conf = conf_threshold
        self.setAutoDelete(True)

    def run(self):
        try:
            self.signals.progress.emit(
                self._page_idx, f'페이지 {self._page_idx + 1} 텍스트 인식 중…')

            if self._engine == 'tesseract':
                items = _run_tesseract_ocr(self._arr, self._lang, self._conf)
            else:
                raise RuntimeError(f'지원하지 않는 OCR 엔진입니다: {self._engine}')

            text = _build_paragraphs(items)
            self.signals.finished.emit(self._page_idx, text)
        except Exception:
            import traceback
            self.signals.error.emit(self._page_idx, traceback.format_exc())
