# core/exporter.py — PDF 저장 / Markdown 변환
from __future__ import annotations
import os
import tempfile
import fitz
import re
from pathlib import Path
from utils.errlog import swallowed


def _page_lines(page: fitz.Page) -> list[tuple[str, float]]:
    """페이지에서 (line_text, font_size) 목록을 반환한다.

    한글 PDF 는 글자 하나씩 별도 위치 오브젝트로 저장되는 경우가 많다.
    rawdict 로 모든 문자의 bbox 를 수집한 뒤:
      1) y_mid ± 3pt 기준으로 같은 시각적 줄을 묶는다.
      2) 같은 줄 내에서 x 순 정렬 후, 인접 char 사이 gap > prev_char_width * 0.4
         이면 공백을 삽입한다.
    """
    try:
        raw = page.get_text('rawdict', flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return []

    # ── 모든 문자 수집: (x0, x1, y_mid, char, fs) ────────────────
    all_chars: list[tuple[float, float, float, str, float]] = []
    for blk in raw.get('blocks', []):
        if blk.get('type') != 0:
            continue
        for line in blk.get('lines', []):
            for span in line.get('spans', []):
                fs = float(span.get('size') or 11)
                for ch in span.get('chars', []):
                    c = ch.get('c', '')
                    if not c or c in ('\n', '\r', '\x00'):
                        continue
                    bbox = ch.get('bbox')
                    if not bbox or len(bbox) < 4:
                        continue
                    x0, y0, x1, y1 = map(float, bbox[:4])
                    y_mid = (y0 + y1) / 2
                    all_chars.append((x0, x1, y_mid, c, fs))

    if not all_chars:
        return []

    # ── y_mid 기준으로 시각적 줄 묶기 (tolerance = 3pt) ─────────
    all_chars.sort(key=lambda t: t[2])   # y 순 정렬

    Y_TOL = 3.0
    buckets: list[list] = []   # 각 원소: [y_mid, [(x0, x1, c, fs), ...]]

    for x0, x1, y_mid, c, fs in all_chars:
        placed = False
        for bkt in reversed(buckets):
            if abs(bkt[0] - y_mid) <= Y_TOL:
                bkt[1].append((x0, x1, c, fs))
                placed = True
                break
        if not placed:
            buckets.append([y_mid, [(x0, x1, c, fs)]])

    # ── 각 줄: x 순 정렬 후 gap 으로 공백 삽입 ───────────────────
    result: list[tuple[str, float]] = []

    for y_mid, chars in sorted(buckets, key=lambda b: b[0]):
        chars_s = sorted(chars, key=lambda t: t[0])   # x 순
        text = chars_s[0][2]
        line_fs = chars_s[0][3]

        for i in range(1, len(chars_s)):
            prev_x0, prev_x1, _, prev_fs = chars_s[i - 1]
            curr_x0, curr_x1, curr_c, curr_fs = chars_s[i]
            char_w = max(prev_x1 - prev_x0, 1.0)   # 이전 글자 폭
            gap    = curr_x0 - prev_x1
            # 이전 글자 폭의 40 % 초과이면 공백
            if gap > char_w * 0.40:
                text += ' '
            text += curr_c
            line_fs = curr_fs   # 마지막 span fs 기준

        text = text.strip()
        if text:
            result.append((text, line_fs))

    return result


def _pdf_name(value: str) -> str:
    safe = value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'({safe})'


def _annot_payload(page: fitz.Page, annot) -> dict:
    info = annot.info or {}
    rect = annot.rect
    subtype = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else 'Annot'
    content = info.get('content') or info.get('title') or info.get('subject') or ''
    return {
        'page': page.number,
        'xref': getattr(annot, 'xref', 0),
        'subtype': str(subtype),
        'rect': [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
        'content': str(content),
        'name': str(info.get('name') or ''),
        'title': str(info.get('title') or ''),
        'subject': str(info.get('subject') or ''),
        'flags': int(getattr(annot, 'flags', 0) or 0),
    }


_MD_LIST_RE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+|[가-힣A-Za-z]\)\s+)')
_MD_SENTENCE_END_RE = re.compile(r'[.!?…]\s*$|[다요죠니다]\.\s*$')


def _normalize_text_line(text: str) -> str:
    return ' '.join((text or '').replace('\u00a0', ' ').split())


def _merge_body_lines(lines: list[str]) -> list[str]:
    """PDF 줄단위 본문을 문단 중심으로 병합해 Markdown 가독성을 높인다."""
    merged: list[str] = []
    buf: list[str] = []

    def flush():
        nonlocal buf
        if buf:
            merged.append(' '.join(buf))
            buf = []

    for raw in lines:
        line = _normalize_text_line(raw)
        if not line:
            flush()
            continue

        if _MD_LIST_RE.match(line):
            flush()
            merged.append(line)
            continue

        if not buf:
            buf = [line]
            continue

        prev = buf[-1]
        if _MD_SENTENCE_END_RE.search(prev):
            flush()
            buf = [line]
        else:
            buf.append(line)

    flush()
    return merged

class Exporter:

    # ── PDF ────────────────────────────────────────────────────────
    def save_pdf(self, doc: fitz.Document, path: str):
        doc.save(path, garbage=4, deflate=True, deflate_images=True)

    # ── 주석 / XFDF ────────────────────────────────────────────────
    def _collect_annots(self, fitz_doc: fitz.Document) -> list[dict]:
        items: list[dict] = []
        for page in fitz_doc:
            try:
                annots = list(page.annots() or [])
            except Exception:
                annots = []
            for annot in annots:
                try:
                    items.append(_annot_payload(page, annot))
                except Exception:
                    continue
        return items

    def export_fdf(self, fitz_doc: fitz.Document, path: str):
        annots = self._collect_annots(fitz_doc)
        lines = ['%FDF-1.2', '1 0 obj', '<<', '/FDF << /Annots [']
        for item in annots:
            rect = ' '.join(f'{v:.2f}' for v in item['rect'])
            lines.extend([
                '<<',
                f"/Page {item['page']}",
                f"/Subtype /{item['subtype']}",
                f"/Rect [{rect}]",
                f"/Contents {_pdf_name(item['content'])}",
            ])
            if item['title']:
                lines.append(f"/T {_pdf_name(item['title'])}")
            if item['subject']:
                lines.append(f"/Subj {_pdf_name(item['subject'])}")
            if item['name']:
                lines.append(f"/NM {_pdf_name(item['name'])}")
            lines.append('>>')
        lines.extend([']', '>>', '>>', 'endobj', 'trailer', '<< /Root 1 0 R >>', '%%EOF'])
        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    def export_xfdf(self, fitz_doc: fitz.Document, path: str):
        import html
        annots = self._collect_annots(fitz_doc)
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve">',
            '  <annots>',
        ]
        for item in annots:
            rect = ','.join(f'{v:.2f}' for v in item['rect'])
            attrs = [
                f'page="{item["page"]}"',
                f'rect="{rect}"',
                f'flags="{item["flags"]}"',
            ]
            if item['title']:
                attrs.append(f'title="{html.escape(item["title"])}"')
            if item['subject']:
                attrs.append(f'subject="{html.escape(item["subject"])}"')
            if item['name']:
                attrs.append(f'name="{html.escape(item["name"])}"')
            attrs_text = ' '.join(attrs)
            tag = item['subtype'].lower()
            lines.append(f'    <{tag} {attrs_text}>')
            if item['content']:
                lines.append(f'      <contents-richtext><body>{html.escape(item["content"])}</body></contents-richtext>')
            lines.append(f'    </{tag}>')
        lines.extend(['  </annots>', '</xfdf>'])
        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    # ── Markdown ───────────────────────────────────────────────────
    def _to_markdown_via_markitdown(self, fitz_doc: fitz.Document, out_path: str) -> bool:
        """MarkItDown으로 PDF -> Markdown 변환 시도. 성공 시 True."""
        try:
            from markitdown import MarkItDown
        except Exception:
            return False

        source_pdf: str | None = None
        temp_pdf: str | None = None
        try:
            doc_name = str(getattr(fitz_doc, 'name', '') or '')
            if doc_name and Path(doc_name).exists() and not fitz_doc.is_dirty:
                source_pdf = doc_name
            else:
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                    temp_pdf = f.name
                fitz_doc.save(temp_pdf)
                source_pdf = temp_pdf

            md = MarkItDown()
            result = None
            for method_name in ('convert', 'convert_local'):
                fn = getattr(md, method_name, None)
                if callable(fn):
                    result = fn(source_pdf)
                    break
            if result is None:
                return False

            text = (
                getattr(result, 'text_content', None)
                or getattr(result, 'markdown', None)
                or getattr(result, 'content', None)
            )
            if text is None:
                text = str(result)
            if not isinstance(text, str):
                text = str(text)

            Path(out_path).write_text(text, encoding='utf-8')
            return True
        except Exception:
            return False
        finally:
            if temp_pdf:
                try:
                    os.unlink(temp_pdf)
                except Exception:
                    swallowed()
    def to_markdown(self, fitz_doc: fitz.Document, path: str,
                    page_range: list[int] | None = None):
        # 기본은 즉시 응답 가능한 기존 변환을 사용한다.
        # MarkItDown은 무거워 UI 프리징이 발생할 수 있어 명시적으로 켠 경우에만 사용.
        use_markitdown = os.environ.get('PDF_EDITOR_USE_MARKITDOWN', '').strip() == '1'
        if page_range is None and use_markitdown and self._to_markdown_via_markitdown(fitz_doc, path):
            return

        pages = page_range or list(range(fitz_doc.page_count))
        lines = []

        for pg_idx in pages:
            page = fitz_doc[pg_idx]
            lines.append(f'\n---\n## 페이지 {pg_idx + 1}\n')

            body_bucket: list[str] = []
            for line_text, fs in _page_lines(page):
                line_text = _normalize_text_line(line_text)
                if not line_text:
                    continue
                if fs >= 18:
                    if body_bucket:
                        lines.extend(_merge_body_lines(body_bucket))
                        body_bucket = []
                    lines.append(f'# {line_text}')
                elif fs >= 14:
                    if body_bucket:
                        lines.extend(_merge_body_lines(body_bucket))
                        body_bucket = []
                    lines.append(f'## {line_text}')
                else:
                    body_bucket.append(line_text)

            if body_bucket:
                lines.extend(_merge_body_lines(body_bucket))

        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    # ── Markdown (테이블 포함) ─────────────────────────────────────
    def to_markdown_with_tables(self, fitz_doc: fitz.Document, path: str,
                                page_range: list[int] | None = None):
        """
        PDF를 Markdown으로 변환하되 표(테이블)를 Markdown 테이블 형식으로 보존.
        fitz.find_tables() (PyMuPDF 1.23+) 사용.
        """
        from .hwp_pdf_extractor import _extract_page
        pages = page_range or list(range(fitz_doc.page_count))
        lines: list[str] = []

        for pg_idx in pages:
            page = fitz_doc[pg_idx]
            lines.append(f'\n---\n## 페이지 {pg_idx + 1}\n')
            lines.extend(_extract_page(page))

        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    # ── 이미지 → PDF ───────────────────────────────────────────────
    def images_to_pdf(self, image_paths: list[str],
                       out_path: str,
                       page_size: tuple[float, float] | None = None,
                       fit: bool = True):
        doc = fitz.open()
        for img_path in image_paths:
            src      = fitz.open(img_path)
            src_rect = src[0].rect
            w = page_size[0] if page_size else src_rect.width
            h = page_size[1] if page_size else src_rect.height
            page = doc.new_page(width=w, height=h)
            if fit and page_size:
                scale = min(w / src_rect.width, h / src_rect.height)
                nw, nh = src_rect.width * scale, src_rect.height * scale
                dest = fitz.Rect((w - nw) / 2, (h - nh) / 2,
                                  (w + nw) / 2, (h + nh) / 2)
            else:
                dest = fitz.Rect(0, 0, w, h)
            page.insert_image(dest, filename=img_path)
            src.close()
        doc.save(out_path, garbage=4, deflate=True)
        doc.close()
