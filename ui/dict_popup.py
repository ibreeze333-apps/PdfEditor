# ui/dict_popup.py — 롤오버 사전 팝업 위젯
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from urllib.parse import quote as _url_quote


class DictPopup(QWidget):
    """커서 근처에 단어 뜻을 표시하는 플로팅 팝업."""

    _STYLE = """
        QWidget#DictPopupRoot {
            background-color: #1E1E2A;
            border: 1.5px solid #5A8FBF;
            border-radius: 6px;
        }
        QLabel#w {
            color: #FFD54F;
            font-weight: bold;
            background: transparent;
            border: none;
        }
        QLabel#d {
            color: #E8E8E8;
            background: transparent;
            border: none;
            line-height: 150%;
        }
        QPushButton#close_btn {
            color: #888;
            font-size: 11px;
            background: transparent;
            border: none;
            padding: 0px;
        }
        QPushButton#close_btn:hover {
            color: #fff;
        }
        QPushButton#web_btn {
            color: #aad4ff;
            font-size: 10px;
            background: transparent;
            border: 1px solid #3a5a7a;
            border-radius: 3px;
            padding: 1px 5px;
        }
        QPushButton#web_btn:hover {
            background: #2a4a6a;
            color: #fff;
        }
    """

    def __init__(self, settings=None):
        super().__init__(None,
                         Qt.WindowType.Tool |
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._settings = settings
        # 불투명 배경 (시스템 투명도 영향 없음)
        self.setObjectName('DictPopupRoot')
        self.setStyleSheet(self._STYLE)

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(12, 8, 10, 10)
        root_lay.setSpacing(5)

        # 헤더: 단어 + 닫기 버튼
        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        self._word_lbl = QLabel()
        self._word_lbl.setObjectName('w')
        hdr.addWidget(self._word_lbl, 1)
        close_btn = QPushButton('✕')
        close_btn.setObjectName('close_btn')
        close_btn.setFixedSize(16, 16)
        close_btn.clicked.connect(self.dismiss)
        hdr.addWidget(close_btn)
        root_lay.addLayout(hdr)

        # 웹 버튼 행 (네이버사전 / 파파고 / 구글번역)
        web_row = QHBoxLayout()
        web_row.setSpacing(4)
        for label, slot in [
            ('네이버사전', self._open_naver_dict),
            ('파파고',     self._open_papago),
            ('구글번역',   self._open_google_translate),
        ]:
            btn = QPushButton(label)
            btn.setObjectName('web_btn')
            btn.setFixedHeight(18)
            btn.clicked.connect(slot)
            web_row.addWidget(btn)
        web_row.addStretch()
        root_lay.addLayout(web_row)

        # 뜻
        self._def_lbl = QLabel()
        self._def_lbl.setObjectName('d')
        self._def_lbl.setWordWrap(True)
        self._def_lbl.setMaximumWidth(400)
        self._def_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        root_lay.addWidget(self._def_lbl)

        # 자동 숨김 타이머
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)
        self._apply_settings_font()

    def _apply_settings_font(self):
        size = getattr(self._settings, 'dict_popup_font_size', 12) if self._settings else 12
        word_font = QFont('Malgun Gothic', max(9, size + 1))
        word_font.setBold(True)
        body_font = QFont('Malgun Gothic', max(8, size))
        self._word_lbl.setFont(word_font)
        self._def_lbl.setFont(body_font)

    def show_at(self, word: str, definition: str, global_pos: QPoint,
                sticky: bool = False):
        """단어·뜻 설정 후 표시. sticky=True면 자동 숨김 없이 수동으로만 닫힘."""
        self._apply_settings_font()
        self._word_lbl.setText(word)
        disp = definition if len(definition) <= 400 else definition[:400] + '…'
        self._def_lbl.setText(disp)
        self.adjustSize()

        # 화면 경계 보정
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        x = global_pos.x() + 20
        y = global_pos.y() + 16
        if x + self.width()  > screen.right():
            x = global_pos.x() - self.width() - 6
        if y + self.height() > screen.bottom():
            y = global_pos.y() - self.height() - 6
        x = max(screen.left(), x)
        y = max(screen.top(), y)

        self.move(x, y)
        self.show()
        self.raise_()

        self._auto_hide.stop()
        if not sticky:
            self._auto_hide.start(4000)   # hover: 4초 후 자동 숨김

    def update_definition(self, word: str, definition: str):
        """비동기 조회 완료 시 뜻만 교체 (같은 단어가 아직 표시 중일 때만)."""
        if not self.isVisible() or self._word_lbl.text() != word:
            return
        disp = definition if len(definition) <= 400 else definition[:400] + '…'
        self._def_lbl.setText(disp)
        self.adjustSize()
        # 읽을 시간 확보 — 자동 숨김 타이머가 돌고 있으면 재시작
        if self._auto_hide.isActive():
            self._auto_hide.start(4000)

    def _open_naver_dict(self):
        word = (self._word_lbl.text() or '').strip()
        if word:
            QDesktopServices.openUrl(QUrl(f'https://dict.naver.com/search.nhn?query={_url_quote(word)}'))

    def _open_papago(self):
        word = (self._word_lbl.text() or '').strip()
        if word:
            QDesktopServices.openUrl(QUrl(f'https://papago.naver.com/?sk=auto&tk=ko&st={_url_quote(word)}'))

    def _open_google_translate(self):
        word = (self._word_lbl.text() or '').strip()
        if word:
            QDesktopServices.openUrl(QUrl(f'https://translate.google.com/?sl=auto&tl=ko&text={_url_quote(word)}&op=translate'))

    def dismiss(self):
        self._auto_hide.stop()
        self.hide()
