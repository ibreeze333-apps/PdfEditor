from __future__ import annotations

import re


LANG_PAIRS: dict[str, tuple[str, str]] = {
    '영어 → 한국어': ('en', 'ko'),
    '한국어 → 영어': ('ko', 'en'),
    '한국어 → 일본어': ('ko', 'ja'),
    '한국어 → 중국어': ('ko', 'zh'),
    '일본어 → 한국어': ('ja', 'ko'),
    '중국어 → 한국어': ('zh', 'ko'),
}


def clean_pdf_text(text: str) -> str:
    text = re.sub(r'─+\s*페이지\s*\d+\s*─+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'doi:\s*\S+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\*†‡§※◆◇●○▲△▶▷■□]{1,4}', '', text)
    text = re.sub(r'(?m)^\s*[-=_─━~\s]{4,}\s*$', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text)]
    filtered = [p for p in paragraphs if len(p) > 5]
    return '\n\n'.join(filtered)


def clean_ocr_text(text: str) -> str:
    text = re.sub(r'─+\s*페이지\s*\d+\s*─+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'doi:\s*\S+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\*†‡§※◆◇●○▲△▶▷■□]{1,4}', '', text)
    text = re.sub(r'(\s*[.·•…]\s*){3,}', ' ', text)
    text = re.sub(r'[ \t]+(?:\d+|[ivxlcdmIVXLCDM]{1,8})\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?m)^\s*(?:\d+|[ivxlcdmIVXLCDM]+)\s*$', '', text)
    text = re.sub(r'(?m)^\s*[-=_─━~\s]{4,}\s*$', '', text)
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text)]
    filtered: list[str] = []
    for p in paragraphs:
        if len(p) <= 5:
            continue
        noise_chars = sum(1 for c in p if c in '. \t·•…')
        if noise_chars / len(p) >= 0.5:
            continue
        filtered.append(p)
    return '\n\n'.join(filtered)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[가-힣a-zA-Z])\.\s+', text)
    result: list[str] = []
    for i, part in enumerate(parts):
        s = part.strip()
        if not s:
            continue
        if i < len(parts) - 1:
            s += '.'
        result.append(s)
    return result if result else [text]


def chunk_paragraphs(text: str, max_chars: int = 400) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if len(p.strip()) > 5]
    units: list[str] = []
    for para in paragraphs:
        if len(para) > max_chars:
            units.extend(_split_sentences(para))
        else:
            units.append(para)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for unit in units:
        if current_len + len(unit) + 2 > max_chars and current:
            chunks.append('\n\n'.join(current))
            current = [unit]
            current_len = len(unit)
        else:
            current.append(unit)
            current_len += len(unit) + 2

    if current:
        chunks.append('\n\n'.join(current))
    return chunks
