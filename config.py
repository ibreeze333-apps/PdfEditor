"""
앱 버전 및 브랜딩 설정.

BUILD_VARIANT 값은 build.py / build_law.py 가 빌드 전에 자동으로 설정합니다.
직접 수정하지 마세요.
"""

APP_VERSION   = '3.5'
BUILD_VARIANT = 'free'   # build 스크립트가 관리

APP_ORG      = 'Breeze333'
APP_SUBTITLE = 'Made by Breeze333'
APP_EXE_NAME = 'PDFEditor'
# 빌드 결과 폴더 (환경변수 PDF_EDITOR_DIST_DIR 로 바꿀 수 있다)
import os as _os
APP_DIST_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'release', 'PDFEditor')


def window_title(filename: str = '', extra: str = '') -> str:
    """타이틀바 문자열 생성."""
    base = f'PdfEditor V.{APP_VERSION}'
    if APP_SUBTITLE:
        base += f'  {APP_SUBTITLE}'
    parts = []
    if filename:
        parts.append(filename)
    if extra:
        parts.append(extra)
    parts.append(base)
    return '  '.join(parts)
