"""
PDF 테이블 추출 — fitz.find_tables() 기반 구조 보존 추출.
annex_parser에서 PDF 포맷 감지 시 호출됨.
"""
from __future__ import annotations

import fitz
from utils.errlog import swallowed


def extract_pdf_with_tables(data: bytes) -> str:
    """PDF 바이트 → 테이블 구조 보존 Markdown."""
    try:
        doc = fitz.open(stream=data, filetype='pdf')
        lines: list[str] = []
        for page in doc:
            page_lines = _extract_page(page)
            lines.extend(page_lines)
            lines.append('')  # 페이지 구분
        doc.close()
        return '\n'.join(lines).strip()
    except Exception as e:
        return f'> ⚠ PDF 파싱 오류: {e}'


def _extract_page(page: fitz.Page) -> list[str]:
    """페이지 한 장 → Markdown 줄 목록 (테이블 포함)."""
    lines: list[str] = []

    # fitz 1.23+ find_tables() 사용
    try:
        tables = page.find_tables()
        table_list = tables.tables if hasattr(tables, 'tables') else list(tables)
    except Exception:
        table_list = []

    # 테이블 bbox 집합 (텍스트 추출 시 중복 제거용)
    table_bboxes = [fitz.Rect(t.bbox) for t in table_list]

    # 페이지 전체 텍스트 블록
    blocks = page.get_text('blocks', sort=True)  # (x0,y0,x1,y1,text,block_no,block_type)

    inserted_tables: set[int] = set()

    for block in blocks:
        x0, y0, x1, y1, text, block_no, block_type = block
        block_rect = fitz.Rect(x0, y0, x1, y1)

        # 이 블록이 테이블 안에 있는지 확인
        table_idx = _find_containing_table(block_rect, table_bboxes)

        if table_idx is not None:
            # 해당 테이블이 아직 삽입 안 됐으면 삽입
            if table_idx not in inserted_tables:
                md_table = _table_to_markdown(table_list[table_idx])
                if md_table:
                    lines.extend(md_table)
                    lines.append('')
                inserted_tables.add(table_idx)
        else:
            # 일반 텍스트 블록
            if block_type == 0 and text.strip():
                for line in text.split('\n'):
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)

    # 아직 삽입 안 된 테이블 (텍스트 블록이 없는 순수 테이블)
    for i, table in enumerate(table_list):
        if i not in inserted_tables:
            md_table = _table_to_markdown(table)
            if md_table:
                lines.extend(md_table)
                lines.append('')

    return lines


def _find_containing_table(rect: fitz.Rect, table_bboxes: list[fitz.Rect]) -> int | None:
    """블록이 속하는 테이블 인덱스 반환. 없으면 None."""
    for i, tbbox in enumerate(table_bboxes):
        if tbbox.intersects(rect):
            # 교집합이 블록 면적의 50% 이상이면 테이블 소속
            inter = tbbox & rect
            if inter.get_area() >= rect.get_area() * 0.5:
                return i
    return None


def _table_to_markdown(table) -> list[str]:
    """fitz Table 객체 → Markdown 테이블 줄 목록."""
    try:
        # fitz 내장 to_markdown() 시도
        md = table.to_markdown()
        if md and md.strip():
            return md.strip().split('\n')
    except Exception:
        swallowed()

    # 직접 변환 폴백
    try:
        rows = table.extract()
        if not rows:
            return []
        max_cols = max(len(r) for r in rows)
        result: list[str] = []
        for i, row in enumerate(rows):
            # 빈 셀 패딩
            padded = list(row) + [''] * (max_cols - len(row))
            cells = [_clean_cell(c) for c in padded]
            result.append('| ' + ' | '.join(cells) + ' |')
            if i == 0:
                result.append('| ' + ' | '.join('---' for _ in padded) + ' |')
        return result
    except Exception:
        return []


def _clean_cell(val) -> str:
    """테이블 셀 값 정리."""
    if val is None:
        return ''
    text = str(val).strip().replace('\n', ' ').replace('|', '\\|')
    return ' '.join(text.split())
