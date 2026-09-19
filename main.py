# main.py — PDF 편집기 진입점
# 실행: python C:/pdf_editor/main.py
from __future__ import annotations
import sys
import os
from utils.errlog import swallowed

# 모듈 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import traceback
from datetime import datetime
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QFontMetrics


def _app_icon() -> QIcon:
    """PyInstaller 패키징 / 개발 환경 모두에서 logo.ico 를 로드."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    ico = os.path.join(base, 'logo.ico')
    if not os.path.exists(ico):          # ico 없으면 png 로 대체
        ico = os.path.join(base, 'logo.png')
    return QIcon(ico)

# ── 로그 파일 설정 ──────────────────────────────────────────────────
# 로그는 프로그램 폴더 옆 logs/ 에 날짜별로 저장
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH  = os.path.join(_LOG_DIR, f'pdf_editor_{datetime.now():%Y%m%d}.log')
_CRASH_LOG = os.path.join(_LOG_DIR, f'fault_{datetime.now():%Y%m%d_%H%M%S}.log')

# faulthandler: C++ segfault(SIGSEGV) 발생 시 스택 트레이스를 파일에 기록.
#
# 주의 — Windows 에서는 faulthandler 가 '처리된' SEH 예외까지 함께 적는다.
# 특히 COM 이 정상 동작 중에 던졌다가 스스로 처리하는 다음 코드들이 자주 남는다:
#   0x8001010d RPC_E_CANTCALLOUT_ININPUTSYNCCALL — 드래그&드롭·네이티브 대화상자
#   0x80040155 REGDB_E_IIDNOTREG                 — 인쇄 대화상자 COM 인터페이스
# 앱은 멀쩡히 계속 실행되지만 파일 이름이 crash_* 라 진짜 다운으로 오해하기 쉽다.
# 그래서 이름을 fault_* 로 바꾸고, 아무것도 안 적힌 파일은 종료 시 지운다.
import atexit as _atexit
import faulthandler as _fh

_crash_file = None
try:
    _crash_file = open(_CRASH_LOG, 'w', encoding='utf-8')
    _fh.enable(file=_crash_file, all_threads=True)
except Exception:
    swallowed()


def _drop_empty_fault_log():
    """아무 예외도 기록되지 않았으면 빈 로그 파일을 남기지 않는다."""
    try:
        if _crash_file is not None:
            _crash_file.flush()
        if os.path.exists(_CRASH_LOG) and os.path.getsize(_CRASH_LOG) == 0:
            _fh.disable()
            if _crash_file is not None:
                _crash_file.close()
            os.remove(_CRASH_LOG)
    except Exception:
        swallowed()


_atexit.register(_drop_empty_fault_log)


def _log_swallowed_summary():
    """종료할 때 '조용히 삼킨 예외' 요약을 로그 끝에 남긴다.

    `except: pass` 로 넘어간 자리들이 어디서 몇 번 터졌는지 한눈에 보인다.
    "눌렀는데 아무 일도 안 일어남" 류 제보가 들어오면 여기부터 본다.
    """
    try:
        from utils.errlog import log_summary
        log_summary()
    except Exception:
        pass        # 종료 경로에서는 조용히


_atexit.register(_log_swallowed_summary)

_file_handler   = logging.FileHandler(_LOG_PATH, encoding='utf-8')
_file_handler.setLevel(logging.INFO)   # DEBUG는 urllib3 등 노이즈로 로그가 수백 MB로 커짐
_stream_handler = logging.StreamHandler(sys.stderr)
_stream_handler.setLevel(logging.WARNING)   # 콘솔엔 경고 이상만 — 시작/종료 시 I/O 감소
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[_file_handler, _stream_handler],
)
# 시끄러운 서드파티 로거는 경고 이상만
for _noisy in ('urllib3', 'PIL', 'paddleocr', 'paddlex'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger('pdf_editor')
logger.info('=== PDF 편집기 시작 ===')


def _cleanup_old_logs(days: int = 14):
    """logs/ 에서 지정 일수보다 오래된 로그 파일 삭제 (디스크 절약)."""
    import time as _time
    cutoff = _time.time() - days * 86400
    try:
        for name in os.listdir(_LOG_DIR):
            if not (name.startswith(('pdf_editor_', 'crash_', 'fault_'))
                    and name.endswith('.log')):
                continue
            p = os.path.join(_LOG_DIR, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass   # 사용 중인 파일 등은 무시
    except OSError:
        swallowed()


_cleanup_old_logs()


def _excepthook(exc_type, exc_value, exc_tb):
    """미처리 예외 → 로그 파일 기록 + 팝업 알림."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical('미처리 예외 발생:\n%s', tb_text)

    # 비상 저장 시도 (데이터 손실 최소화)
    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            if hasattr(w, '_emergency_save'):
                try:
                    w._emergency_save()
                except Exception:
                    swallowed()

        from PySide6.QtWidgets import QMessageBox, QPushButton
        msg = QMessageBox()
        msg.setWindowTitle('오류 발생')
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText(
            f'예상치 못한 오류가 발생했습니다.\n'
            f'작업 내용을 자동 저장했습니다. 재시작하면 복구 가능합니다.\n\n'
            f'📄 로그: {_LOG_PATH}')
        msg.setDetailedText(tb_text)
        open_btn = msg.addButton('📂 로그 폴더 열기', QMessageBox.ButtonRole.ActionRole)
        msg.addButton('닫기', QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == open_btn:
            os.startfile(_LOG_DIR)


sys.excepthook = _excepthook


def _install_win_crash_handler():
    """Windows에서 ACCESS VIOLATION(segfault) 발생 시 비상 저장 시도."""
    try:
        import ctypes, ctypes.wintypes as _wt
        EXCEPTION_CONTINUE_SEARCH = 0
        _EXCEPTION_CALLBACKS = []   # GC 방지용 레퍼런스 보관

        EXCEPTION_HANDLER = ctypes.CFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,  # EXCEPTION_POINTERS*
        )

        def _handler(exc_info_ptr):
            # 비상 저장
            try:
                _app = QApplication.instance()
                if _app:
                    for _w in _app.topLevelWidgets():
                        if hasattr(_w, '_emergency_save'):
                            try:
                                _w._emergency_save()
                            except Exception:
                                swallowed()
            except Exception:
                swallowed()
            return EXCEPTION_CONTINUE_SEARCH

        cb = EXCEPTION_HANDLER(_handler)
        _EXCEPTION_CALLBACKS.append(cb)  # GC 방지

        kernel32 = ctypes.windll.kernel32
        kernel32.SetUnhandledExceptionFilter(cb)
    except Exception:
        pass   # Windows 외 환경 또는 ctypes 실패 → 무시


def _make_splash() -> QSplashScreen:
    """로고 + 제목 + Breeze333 스플래시 화면."""
    w, h = 500, 220
    pix = QPixmap(w, h)
    pix.fill(QColor('#1e1e2e'))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # ── 배경 둥근 테두리 ──────────────────────────────────────────
    painter.setPen(QColor('#89b4fa'))
    painter.setBrush(QColor('#1e1e2e'))
    painter.drawRoundedRect(2, 2, w - 4, h - 4, 14, 14)

    # ── 로고 이미지 (왼쪽) ────────────────────────────────────────
    logo_size = 120
    logo_x    = 28
    logo_y    = (h - logo_size) // 2

    base = getattr(__import__('sys'), '_MEIPASS',
                   os.path.dirname(os.path.abspath(__file__)))
    logo_path = os.path.join(base, 'logo.png')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(base, 'logo.ico')

    logo_pix = QPixmap(logo_path)
    if not logo_pix.isNull():
        logo_pix = logo_pix.scaled(
            logo_size, logo_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # 원형 클리핑
        from PySide6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addEllipse(logo_x, logo_y, logo_size, logo_size)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(logo_x, logo_y, logo_pix)
        painter.restore()
        # 원형 테두리
        painter.setPen(QColor('#89b4fa'))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        from PySide6.QtCore import QRectF
        painter.drawEllipse(QRectF(logo_x, logo_y, logo_size, logo_size))

    # ── 텍스트 영역 (오른쪽) ─────────────────────────────────────
    tx = logo_x + logo_size + 22
    tw = w - tx - 18

    # 앱 제목
    title_font = QFont('Malgun Gothic', 22, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.setPen(QColor('#cdd6f4'))
    painter.drawText(tx, 38, tw, 52,
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     'PDF 편집기')

    # 구분선
    painter.setPen(QColor('#313244'))
    painter.drawLine(tx, 98, tx + tw, 98)

    # 제작자
    brand_font = QFont('Malgun Gothic', 12, QFont.Weight.Bold)
    painter.setFont(brand_font)
    painter.setPen(QColor('#89b4fa'))
    painter.drawText(tx, 104, tw, 34,
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     'Breeze333')

    # 버전 (config에서 가져오기, 실패 시 빈 문자열)
    try:
        import config as _cfg_mod
        ver_str = f'v{_cfg_mod.APP_VERSION}'
    except Exception:
        ver_str = ''
    if ver_str:
        ver_font = QFont('Malgun Gothic', 10)
        painter.setFont(ver_font)
        painter.setPen(QColor('#45475a'))
        painter.drawText(tx, 104, tw, 34,
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         ver_str)

    # 로딩 텍스트
    sub_font = QFont('Malgun Gothic', 10)
    painter.setFont(sub_font)
    painter.setPen(QColor('#585b70'))
    painter.drawText(tx, 148, tw, 36,
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     '로딩 중…')

    painter.end()

    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    return splash


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')   # Windows 네이티브 스타일 대신 Qt Fusion — 메뉴바 커스텀 위젯 지원
    import config
    app.setApplicationName('PdfEditor')
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.APP_ORG)
    app.setWindowIcon(_app_icon())

    # 기본 폰트 설정 (한국어) — 13pt로 전체 UI 크기 확대
    font = QFont('Malgun Gothic', 13)
    app.setFont(font)

    # 작은 화면에서 창·대화상자가 화면 밖으로 넘치지 않게 (ui/screen_fit.py)
    from ui.screen_fit import install_screen_fit
    install_screen_fit(app)

    # 고DPI 지원
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    # 스플래시 화면 — 무거운 import 전에 즉시 표시
    splash = _make_splash()
    splash.show()
    app.processEvents()

    # GUI 멈춤 감지 워치독 — 5초 이상 무응답이면 logs/freeze_*.log 에
    # 전체 스레드 스택을 덤프해 원인 추적 가능
    from utils.freeze_watchdog import start_watchdog
    start_watchdog(_LOG_DIR)

    # 여기서 fitz/MainWindow 등 무거운 모듈 로딩
    from ui.main_window import MainWindow

    _install_win_crash_handler()   # Windows segfault → 비상 저장 시도

    win = MainWindow()
    win.showMaximized()
    splash.finish(win)

    # 커맨드라인으로 파일 열기 (파일 연결/드래그 실행 포함)
    # open_path_checked: 위장 파일 검사를 거쳐 이미지/PDF 를 판별해 연다
    if len(sys.argv) > 1:
        _path = sys.argv[1]
        if os.path.exists(_path):
            win.open_path_checked(_path)
        else:
            logger.warning('명령줄 인자 파일이 없습니다: %s', _path)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
