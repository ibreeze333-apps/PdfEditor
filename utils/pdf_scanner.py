# utils/pdf_scanner.py — PDF 내부 악성 콘텐츠 스캐너
"""
fitz(PyMuPDF)로 PDF 오브젝트 트리를 순회하며
악성코드가 숨어있을 수 있는 위험 요소를 탐지한다.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field

# ── 위험 키 정의 ───────────────────────────────────────────────────────
_DANGEROUS_KEYS: dict[str, tuple[str, str]] = {
    # key: (한글 설명, 위험도)  위험도: 'high' | 'medium'
    '/JS':           ('JavaScript 코드',              'high'),
    '/JavaScript':   ('JavaScript 코드',              'high'),
    '/OpenAction':   ('파일 열기 시 자동 실행 액션',  'high'),
    '/Launch':       ('외부 프로그램 실행 명령',       'high'),
    '/AA':           ('자동 추가 액션 (AA)',           'medium'),
    '/EmbeddedFile': ('내장 파일 포함',                'medium'),
    '/RichMedia':    ('리치 미디어 (Flash 등)',        'medium'),
    '/XFA':          ('XFA 폼 (악용 가능한 XML 폼)',  'medium'),
    '/Sound':        ('사운드 자동 재생',              'medium'),
    '/Movie':        ('무비 자동 재생',                'medium'),
}


@dataclass
class PdfScanResult:
    findings: list[tuple[str, str, str]] = field(default_factory=list)
    # findings: [(key, 설명, 위험도), ...]
    error: str = ''

    @property
    def is_clean(self) -> bool:
        return len(self.findings) == 0 and not self.error

    @property
    def has_high(self) -> bool:
        return any(level == 'high' for _, _, level in self.findings)

    def summary(self) -> str:
        """경고창에 표시할 문자열."""
        lines = ['⚠ PDF 내부에서 위험 요소가 발견됐습니다:\n']
        for key, desc, level in self.findings:
            icon = '🔴' if level == 'high' else '🟡'
            lines.append(f'  {icon} {desc}  ({key})')
        lines.append('\n악성 PDF일 수 있습니다. 계속 열겠습니까?')
        return '\n'.join(lines)


def scan(path: str | Path) -> PdfScanResult:
    """
    PDF 파일의 모든 오브젝트를 순회하며 위험 키를 탐지한다.

    - fitz 미설치 또는 파싱 불가 파일 → 빈 결과 반환 (오픈 시 fitz가 처리)
    - 정상 PDF → is_clean = True
    - 위험 요소 발견 → findings 에 항목 추가
    """
    result = PdfScanResult()
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        found_keys: set[str] = set()

        n = doc.xref_length()
        for xref in range(1, n):
            try:
                keys = doc.xref_get_keys(xref)
                for k in keys:
                    if k in _DANGEROUS_KEYS and k not in found_keys:
                        desc, level = _DANGEROUS_KEYS[k]
                        result.findings.append((k, desc, level))
                        found_keys.add(k)
            except Exception:
                continue

        doc.close()
    except Exception as e:
        result.error = str(e)

    return result
