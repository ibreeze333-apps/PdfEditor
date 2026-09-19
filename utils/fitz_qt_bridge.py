# utils/fitz_qt_bridge.py — fitz.Pixmap ↔ Qt 변환 유틸리티
from __future__ import annotations
import fitz
from PySide6.QtGui import QImage, QPixmap


def pixmap_to_qimage(pix: fitz.Pixmap) -> QImage:
    """fitz.Pixmap → QImage (RGB888). pix의 수명에서 독립된 copy 반환."""
    img = QImage(
        pix.samples, pix.width, pix.height,
        pix.stride, QImage.Format.Format_RGB888,
    )
    return img.copy()   # fitz Pixmap 수명 독립


def pixmap_to_qpixmap(pix: fitz.Pixmap) -> QPixmap:
    return QPixmap.fromImage(pixmap_to_qimage(pix))


def render_page(page: fitz.Page, zoom: float = 1.0,
                clip: fitz.Rect | None = None) -> QImage:
    """페이지를 QImage로 렌더링. clip 지정 시 해당 영역만."""
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    img = pixmap_to_qimage(pix)
    del pix   # fitz Pixmap 즉시 해제 (메모리 절약)
    return img


def extract_page_text(page: fitz.Page) -> str:
    """PDF 페이지에서 텍스트를 추출한다 (OCR 패널 fast 모드와 동일한 방식).

    글자 bbox 간격을 기준으로 단어 사이 공백을 삽입하며,
    블록(문단) 경계는 '\\n\\n' 으로 구분해 문단 구조를 보존한다.

    Returns:
        블록 단위로 나뉜 텍스트. 텍스트 레이어가 없으면 빈 문자열.
    """
    d = page.get_text('rawdict', sort=True)
    paras: list[str] = []
    for block in d.get('blocks', []):
        if block.get('type') != 0:   # 이미지 블록 무시
            continue
        block_lines: list[str] = []
        for line in block.get('lines', []):
            line_text = ''
            prev_x1: float | None = None
            for span in line.get('spans', []):
                size = span.get('size', 12) or 12
                for ch in span.get('chars', []):
                    x0 = ch['bbox'][0]
                    # 앞 글자와 간격이 폰트 크기의 25% 이상이면 공백 삽입
                    if prev_x1 is not None and (x0 - prev_x1) > size * 0.25:
                        line_text += ' '
                    line_text += ch.get('c', '')
                    prev_x1 = ch['bbox'][2]
            if line_text.strip():
                block_lines.append(line_text.strip())
        if block_lines:
            paras.append(' '.join(block_lines))   # 블록 내 줄들은 공백 연결
    return '\n\n'.join(paras)                     # 블록(문단) 구분은 \n\n
