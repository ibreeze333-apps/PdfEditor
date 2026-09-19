# utils/file_type.py — Magika 기반 파일 타입 감지 헬퍼
"""
Magika(Google)를 이용해 파일 내용을 분석하고 확장자와의 불일치를 감지한다.
Magika가 설치되지 않은 환경에서는 조용히 None을 반환해 기존 흐름을 유지한다.
"""
from __future__ import annotations
from pathlib import Path

# PDF / 이미지 그룹 매핑
_PDF_LABELS   = {'pdf'}
_IMAGE_LABELS = {'png', 'jpeg', 'jpg', 'gif', 'bmp', 'tiff', 'webp', 'ico'}
_TEXT_LABELS  = {'txt', 'md', 'rst', 'csv', 'tsv', 'html', 'xml', 'json'}

# 위험 파일 타입 — 어떤 확장자로 위장하든 즉시 차단.
#
# 여기 적는 문자열은 Magika 가 실제로 내놓는 라벨과 정확히 같아야 한다.
# 'bat', 'ps1', 'js' 처럼 그럴듯하지만 존재하지 않는 이름을 적으면 영영
# 걸리지 않는다(실제로 그런 상태로 있었다). Magika 라벨 목록과 대조하는
# 테스트는 tests/test_file_type.py 참고.
_DANGEROUS_LABELS = {
    # ── 실행 파일 ──
    'pebin',           # Windows PE (.exe, .dll, .scr …)
    'elf',             # Linux/Android
    'macho',           # macOS
    'msi',             # Windows 설치 패키지
    'apk',             # 안드로이드 패키지
    'jar',             # Java 실행 아카이브
    'javabytecode',    # .class
    'pythonbytecode',  # .pyc
    # ── 더블클릭만으로 실행되는 스크립트 ──
    'batch',           # .bat / .cmd
    'powershell',      # .ps1
    'javascript',      # .js (Windows Script Host)
    'vba',             # VBA / VBScript 매크로
    'shell',           # .sh
    # ── 기타 ──
    'lnk',             # 바로가기 — 임의 명령을 가리킬 수 있다
    'chm',             # 도움말 파일 — 스크립트 실행 경로가 있다
    'winregistry',     # .reg — 레지스트리를 건드린다
}

# 확장자 → 기대 그룹
_EXT_GROUP: dict[str, str] = {}
for _e in ('.pdf',):
    _EXT_GROUP[_e] = 'pdf'
for _e in ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp', '.gif'):
    _EXT_GROUP[_e] = 'image'

_magika_instance = None   # 싱글톤 — 모델은 한 번만 로딩


def _get_magika():
    """Magika 싱글톤을 반환한다. 미설치/로딩 실패면 None.

    실패 시 조용히 넘어가면 위장 실행파일 검사가 죽은 채로 배포될 수 있으므로
    (빌드에서 onnxruntime 이 빠졌던 사례) 반드시 로그에 남긴다.
    """
    global _magika_instance
    if _magika_instance is None:
        try:
            from magika import Magika
            _magika_instance = Magika()
        except Exception:
            import logging
            logging.getLogger('pdf_editor').warning(
                '[file_type] Magika 로딩 실패 — 파일 위장 검사가 비활성화됩니다. '
                '(onnxruntime 번들 여부를 확인하세요)', exc_info=True)
            _magika_instance = False   # 미설치 표시
    return _magika_instance if _magika_instance else None


def prewarm() -> None:
    """앱 시작 시 백그라운드에서 호출해 모델을 메모리에 올려둔다."""
    _get_magika()


def detect(path: str | Path) -> str | None:
    """
    파일 내용을 분석해 Magika label을 반환한다.
    예: 'pdf', 'jpeg', 'png', 'zip', 'python' …
    Magika 미설치 또는 오류 시 None.
    """
    m = _get_magika()
    if m is None:
        return None
    try:
        result = m.identify_path(Path(path))
        return result.output.label
    except Exception:
        return None


class FileCheckResult:
    """check_mismatch 반환값 — 심각도와 메시지를 함께 전달."""
    __slots__ = ('severity', 'message', 'label')

    SAFE    = 'safe'      # 문제 없음
    WARN    = 'warn'      # 경고 (계속 열기 가능)
    ASK     = 'ask'       # 질문 (PDF로 열겠습니까?)
    BLOCK   = 'block'     # 차단 (열기 금지)

    def __init__(self, severity: str, message: str, label: str = ''):
        self.severity = severity
        self.message  = message
        self.label    = label


def check_mismatch(path: str | Path) -> FileCheckResult:
    """
    파일 내용을 분석해 FileCheckResult를 반환한다.

    severity:
      SAFE  — 정상, 아무 조치 불필요
      WARN  — 불일치 경고 표시 후 열기 계속
      ASK   — 사용자에게 PDF로 열지 물어봄
      BLOCK — 위험 파일, 열기 차단
    """
    p     = Path(path)
    ext   = p.suffix.lower()
    label = detect(p)

    if label is None:
        return FileCheckResult(FileCheckResult.SAFE, '', '')

    # ── 위험 파일 즉시 차단 ─────────────────────────────────────
    if label in _DANGEROUS_LABELS:
        label_kor = {
            'pebin':          'Windows 실행파일(EXE/DLL)',
            'elf':            'Linux 실행파일',
            'macho':          'macOS 실행파일',
            'msi':            'Windows 설치 패키지(MSI)',
            'apk':            '안드로이드 앱(APK)',
            'jar':            'Java 실행 파일(JAR)',
            'javabytecode':   'Java 바이트코드(CLASS)',
            'pythonbytecode': 'Python 바이트코드(PYC)',
            'batch':          '배치 스크립트(BAT/CMD)',
            'powershell':     'PowerShell 스크립트',
            'javascript':     'JavaScript',
            'vba':            'VBA/VBScript 매크로',
            'shell':          '셸 스크립트',
            'lnk':            '바로가기(LNK)',
            'chm':            '도움말 파일(CHM)',
            'winregistry':    '레지스트리 파일(REG)',
        }.get(label, f'실행 가능 파일({label.upper()})')
        return FileCheckResult(
            FileCheckResult.BLOCK,
            f'⛔ 위험한 파일입니다!\n\n'
            f'확장자는 {ext} 이지만 실제 내용은\n'
            f'[{label_kor}] 입니다.\n\n'
            f'악성코드나 위장 파일일 수 있습니다.\n'
            f'이 파일은 열 수 없습니다.',
            label,
        )

    # ── 형식 불일치 경고 ─────────────────────────────────────────
    ext_group   = _EXT_GROUP.get(ext)
    label_group = (
        'pdf'   if label in _PDF_LABELS   else
        'image' if label in _IMAGE_LABELS else
        'other'
    )

    if ext_group is None or ext_group == label_group:
        return FileCheckResult(FileCheckResult.SAFE, '', label)

    label_kor = {
        'pdf':  'PDF 문서',
        'jpeg': 'JPEG 이미지', 'jpg':  'JPEG 이미지',
        'png':  'PNG 이미지',  'gif':  'GIF 이미지',
        'bmp':  'BMP 이미지',  'tiff': 'TIFF 이미지',
        'webp': 'WebP 이미지', 'zip':  'ZIP 압축 파일',
        'docx': 'Word 문서',   'xlsx': 'Excel 문서',
    }.get(label, label.upper())

    if label_group == 'pdf' and ext_group == 'image':
        return FileCheckResult(
            FileCheckResult.ASK,
            f'확장자는 {ext}이지만 실제 내용은 {label_kor}입니다.\nPDF로 열겠습니까?',
            label,
        )
    return FileCheckResult(
        FileCheckResult.WARN,
        f'확장자는 {ext}이지만 실제 파일 내용이 {label_kor}입니다.\n'
        f'파일이 손상됐거나 잘못된 확장자일 수 있습니다.',
        label,
    )
