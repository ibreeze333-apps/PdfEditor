# ui/dialogs/preferences_dialog.py - 앱 환경 설정 다이얼로그
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QCheckBox, QLabel, QPushButton, QDialogButtonBox,
    QDoubleSpinBox, QColorDialog, QFileDialog, QLineEdit, QSpinBox, QComboBox,
    QWidget, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from utils.settings import AppSettings
from utils.annot_style import tool_style, apply_settings_defaults


_BOOK_PRESETS = {
    'classic': ('베이지', '#e7dcc5', 18),
    'hardcover': ('샌드 브라운', '#d8c7aa', 24),
    'notebook': ('아이보리', '#f2eddc', 10),
    'aged': ('앤틱 브라운', '#cdb792', 30),
}

# (name, 표시라벨, has_opacity, has_width)
_TOOL_ROWS = [
    ('highlight',     '🖌 형광펜',   True,  False),
    ('underline',     '📏 밑줄',     False, True),
    ('strikethrough', '~~취소선~~',  False, True),
    ('pencil',        '✏ 연필',      False, True),
    ('line',          '➖ 직선',     False, True),
    ('arrow',         '➡ 화살표',   False, True),
    ('shape',         '\ub3c4\ud615',     False, True),
    ('mosaic',        '\ub9c8\ucee4',     False, False),
]

_BLUR_MODE_CHOICES = [
    ('gaussian', '\uac15\ud55c \ube14\ub7ec'),
    ('pixelate', '\ud53d\uc140\ud654'),
    ('noise', '\ub178\uc774\uc988 \uc11e\uae30'),
    ('downscale', '\ucd95\uc18c \ud6c4 \uc7ac\ud655\ub300'),
]


class PreferencesDialog(QDialog):
    """기본 설정 + 도구 기본 스타일 설정 다이얼로그."""

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._tool_colors: dict[str, list] = {}
        self._tool_opacities: dict[str, QDoubleSpinBox] = {}
        self._tool_widths: dict[str, QDoubleSpinBox] = {}
        self._book_preset = getattr(self._settings, 'book_preset', 'classic')
        self._setui()
        self.setWindowTitle('기본 설정')
        self.setMinimumWidth(560)
        self.resize(580, 680)

    def _setui(self):
        # 전체 레이아웃: 스크롤 영역 + 하단 고정 버튼
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 스크롤 가능한 내용 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 12, 12, 12)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # 하단 구분선 + 버튼박스 (스크롤 밖 고정)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet('background: #ccc;')
        root.addWidget(sep)

        btn_row = QWidget()
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(12, 8, 12, 8)
        reset_btn = QPushButton('↺ 기본값으로 초기화')
        reset_btn.setToolTip('이 창의 설정을 앱 기본값으로 되돌립니다.\n'
                             '확인을 눌러야 실제로 저장됩니다.')
        reset_btn.clicked.connect(self._restore_defaults)
        btn_lay.addWidget(reset_btn)
        btn_lay.addStretch(1)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save_and_accept)
        bb.rejected.connect(self.reject)
        btn_lay.addWidget(bb)
        root.addWidget(btn_row)

        save_grp = QGroupBox('저장 옵션')
        save_lay = QVBoxLayout(save_grp)
        self._cb_dual = QCheckBox('저장 시 원본 파일 자동 백업')
        self._cb_dual.setChecked(self._settings.save_dual_copy)
        save_lay.addWidget(self._cb_dual)
        hint = QLabel(
            '  예) 문서.pdf 저장 시  →  문서_original.pdf (원본 보존)  +  문서.pdf (새 저장)\n'
            '  ※ 동일 폴더에 저장됩니다.')
        hint.setStyleSheet('color: #666; font-size: 11px;')
        hint.setWordWrap(True)
        save_lay.addWidget(hint)

        self._cb_subset = QCheckBox('글꼴에서 쓴 글자만 남기기 (권장)')
        self._cb_subset.setChecked(self._settings.subset_fonts)
        save_lay.addWidget(self._cb_subset)
        subset_hint = QLabel(
            '  PDF 표준 방식입니다. 끄면 글꼴 파일이 통째로 들어가\n'
            '  글자 몇 개만 고쳐도 파일이 몇 배로 커집니다 (한글 글꼴은 7MB 이상).\n'
            '  ※ 이 문서를 글꼴이 설치되지 않은 컴퓨터의 다른 프로그램에서\n'
            '     새 글자를 타이핑해 편집할 일이 있다면 끄세요.')
        subset_hint.setStyleSheet('color: #666; font-size: 11px;')
        subset_hint.setWordWrap(True)
        save_lay.addWidget(subset_hint)
        lay.addWidget(save_grp)

        tool_grp = QGroupBox('도구 기본 스타일')
        tool_outer = QVBoxLayout(tool_grp)
        grid = QGridLayout()
        grid.setColumnStretch(0, 2)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for col, text in enumerate(['도구', '색상', '불투명도', '굵기(pt)']):
            lbl = QLabel(f'<b>{text}</b>')
            grid.addWidget(lbl, 0, col)
        saved = self._settings.tool_defaults
        for row, (name, label, has_op, has_w) in enumerate(_TOOL_ROWS, 1):
            st = tool_style(name)
            saved_vals = saved.get(name, {})
            cur_color = QColor(saved_vals['color']) if 'color' in saved_vals else st.color
            grid.addWidget(QLabel(label), row, 0)
            btn = QPushButton()
            btn.setFixedSize(48, 24)
            btn.setStyleSheet(f'background-color: {cur_color.name()};')
            self._tool_colors[name] = [cur_color, btn]
            btn.clicked.connect(lambda _, n=name: self._pick_tool_color(n))
            grid.addWidget(btn, row, 1)
            if has_op:
                op_val = saved_vals.get('opacity', st.opacity)
                sb = QDoubleSpinBox()
                sb.setRange(0.05, 1.0)
                sb.setSingleStep(0.05)
                sb.setDecimals(2)
                sb.setValue(op_val)
                sb.setFixedWidth(72)
                self._tool_opacities[name] = sb
                grid.addWidget(sb, row, 2)
            if has_w:
                w_val = saved_vals.get('width', st.width)
                sb = QDoubleSpinBox()
                sb.setRange(0.5, 20.0)
                sb.setSingleStep(0.5)
                sb.setDecimals(1)
                sb.setValue(w_val)
                sb.setFixedWidth(72)
                self._tool_widths[name] = sb
                grid.addWidget(sb, row, 3)
        tool_outer.addLayout(grid)
        lay.addWidget(tool_grp)

        blur_grp = QGroupBox('\ube14\ub7ec \uae30\ubcf8\uac12')
        blur_lay = QGridLayout(blur_grp)
        blur_lay.setHorizontalSpacing(10)
        blur_lay.setVerticalSpacing(8)
        blur_lay.addWidget(QLabel('\ubc29\uc2dd:'), 0, 0)
        self._blur_mode_cb = QComboBox()
        for key, label in _BLUR_MODE_CHOICES:
            self._blur_mode_cb.addItem(label, key)
        current_blur_mode = getattr(self._settings, 'blur_mode', 'gaussian') or 'gaussian'
        blur_idx = self._blur_mode_cb.findData(current_blur_mode)
        self._blur_mode_cb.setCurrentIndex(max(0, blur_idx))
        blur_lay.addWidget(self._blur_mode_cb, 0, 1)
        blur_lay.addWidget(QLabel('\uac15\ub3c4:'), 1, 0)
        self._blur_strength_sb = QSpinBox()
        self._blur_strength_sb.setRange(4, 40)
        self._blur_strength_sb.setValue(int(getattr(self._settings, 'blur_strength', 12) or 12))
        blur_lay.addWidget(self._blur_strength_sb, 1, 1)
        blur_hint = QLabel('\ub9c8\ucee4 \uae30\ubcf8\uc0c9\uc740 \uc704 \ub3c4\uad6c \uae30\ubcf8 \uc2a4\ud0c0\uc77c\uc5d0\uc11c \uc124\uc815\ud569\ub2c8\ub2e4.')
        blur_hint.setStyleSheet('color: #777; font-size: 11px;')
        blur_lay.addWidget(blur_hint, 2, 0, 1, 2)
        lay.addWidget(blur_grp)

        scroll_hint = QLabel('▼  아래로 스크롤하면 사전 설정·책 보기 등 추가 설정이 있습니다')
        scroll_hint.setStyleSheet('color: #888; font-size: 10px; padding: 4px 0;')
        lay.addWidget(scroll_hint)

        dict_grp = QGroupBox('롤오버 사전')
        dict_lay = QVBoxLayout(dict_grp)
        self._cb_dict = QCheckBox('텍스트 위에 마우스를 올리면 사전 뜻 표시')
        self._cb_dict.setChecked(self._settings.dict_enabled)
        dict_lay.addWidget(self._cb_dict)
        self._cb_dict_english_only = QCheckBox('\uac80\uc0c9 \ub2e8\uc5b4\ub97c \uc601\uc5b4\ub9cc\uc73c\ub85c \uc81c\ud55c')
        self._cb_dict_english_only.setChecked(getattr(self._settings, 'dict_english_only', False))
        dict_lay.addWidget(self._cb_dict_english_only)
        # 온라인 사전 대체 체크박스
        self._cb_online = QCheckBox('온라인 사전으로 대체  (네이버사전 뜻 자동 표시)')
        self._cb_online.setChecked(getattr(self._settings, 'dict_online_mode', False))
        self._cb_online.setStyleSheet('color: #1a5fa8; font-weight: bold;')
        self._cb_online.stateChanged.connect(self._on_online_mode_changed)
        dict_lay.addWidget(self._cb_online)

        online_hint = QLabel(
            '  ※ 단어 위에 마우스를 올리면 네이버사전 뜻이 팝업에 바로 표시됩니다 '
            '(로컬 사전 파일 불필요, 인터넷 연결 필요).')
        online_hint.setStyleSheet('color: #888; font-size: 10px;')
        dict_lay.addWidget(online_hint)

        # 로컬 사전 파일 영역 (온라인 모드일 때 비활성화)
        self._dict_file_widget = QWidget()
        file_lay = QVBoxLayout(self._dict_file_widget)
        file_lay.setContentsMargins(0, 0, 0, 0)
        file_lay.setSpacing(4)
        path_ly = QHBoxLayout()
        path_ly.addWidget(QLabel('사전 파일:'))
        _dict_display = (getattr(self._settings, 'dict_paths', []) or [self._settings.dict_path])
        _dict_display = _dict_display[0] if _dict_display and _dict_display[0] else ''
        self._dict_path_ed = QLineEdit(_dict_display)
        self._dict_path_ed.setPlaceholderText('.mdic / .mdict / .mdx / .dict(.dz) / .ifo / .tsv / .json')
        self._dict_path_ed.setReadOnly(True)
        path_ly.addWidget(self._dict_path_ed, 1)
        browse_btn = QPushButton('찾기…')
        browse_btn.setMinimumWidth(64)
        browse_btn.clicked.connect(self._browse_dict)
        path_ly.addWidget(browse_btn)
        unload_btn = QPushButton('해제')
        unload_btn.setMinimumWidth(52)
        unload_btn.clicked.connect(self._unload_dict)
        path_ly.addWidget(unload_btn)
        file_lay.addLayout(path_ly)
        self._dict_status = QLabel()
        self._dict_status.setStyleSheet('color: #666; font-size: 11px;')
        self._refresh_dict_status()
        file_lay.addWidget(self._dict_status)
        fmt_hint = QLabel('지원 형식: MDIC, MDICT · MDX (MDict), StarDict (.dict/.ifo), TSV, JSON')
        fmt_hint.setStyleSheet('color: #888; font-size: 10px;')
        file_lay.addWidget(fmt_hint)
        dict_lay.addWidget(self._dict_file_widget)

        popup_fs_ly = QHBoxLayout()
        popup_fs_ly.addWidget(QLabel('롤오버 글자 크기:'))
        self._dict_popup_fs = QSpinBox()
        self._dict_popup_fs.setRange(8, 28)
        self._dict_popup_fs.setValue(getattr(self._settings, 'dict_popup_font_size', 12))
        popup_fs_ly.addWidget(self._dict_popup_fs)
        popup_fs_ly.addStretch()
        dict_lay.addLayout(popup_fs_ly)
        lay.addWidget(dict_grp)

        # 초기 상태 반영
        self._on_online_mode_changed()

        book_grp = QGroupBox('책 보기')
        book_lay = QGridLayout(book_grp)
        book_lay.setHorizontalSpacing(10)
        book_lay.setVerticalSpacing(8)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_row.addWidget(QLabel('바탕색:'))
        self._book_preset_btns = {}
        for key, (label, _color, _strength) in _BOOK_PRESETS.items():
            btn = QPushButton(label)
            btn.setMinimumWidth(68)
            btn.clicked.connect(lambda _=False, k=key: self._apply_book_preset(k))
            preset_row.addWidget(btn)
            self._book_preset_btns[key] = btn
        preset_row.addStretch()
        book_lay.addLayout(preset_row, 0, 0, 1, 3)
        book_lay.addWidget(QLabel('직접 색상:'), 1, 0)
        self._book_color = QColor(getattr(self._settings, 'book_bg_color', '#e7dcc5'))
        self._book_color_btn = QPushButton()
        self._book_color_btn.setFixedSize(64, 26)
        self._book_color_btn.setStyleSheet(f'background-color: {self._book_color.name()};')
        self._book_color_btn.clicked.connect(self._pick_book_color)
        book_lay.addWidget(self._book_color_btn, 1, 1)
        self._book_color_lbl = QLabel(self._book_color.name())
        self._book_color_lbl.setStyleSheet('color: #666;')
        book_lay.addWidget(self._book_color_lbl, 1, 2)
        book_lay.addWidget(QLabel('페이지 질감 강도:'), 2, 0)
        self._book_texture_sb = QSpinBox()
        self._book_texture_sb.setRange(0, 40)
        self._book_texture_sb.setValue(int(getattr(self._settings, 'book_texture_strength', 18)))
        self._book_texture_sb.setSuffix('%')
        book_lay.addWidget(self._book_texture_sb, 2, 1)
        hint_lbl = QLabel('0 = 질감 없음, 40 = 진한 종이 질감')
        hint_lbl.setStyleSheet('color: #777; font-size: 11px;')
        book_lay.addWidget(hint_lbl, 2, 2)
        lay.addWidget(book_grp)
        lay.addStretch()

    def _restore_defaults(self):
        """이 창에 보이는 설정을 앱 기본값으로 되돌린다 (확인 시 저장).

        사전 파일 경로·API 키·최근 파일 등 사용자 데이터는 건드리지 않는다.
        """
        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self, '기본값으로 초기화',
            '이 창의 설정(저장 옵션·도구 스타일·블러·사전 옵션·책 보기)을\n'
            '기본값으로 되돌리시겠습니까?\n\n'
            '· 사전 파일 경로와 API 키는 유지됩니다.\n'
            '· 확인(OK)을 눌러야 실제로 저장됩니다 — 취소하면 되돌아갑니다.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return

        from dataclasses import fields as dc_fields, MISSING
        d = {f.name: f.default for f in dc_fields(AppSettings)
             if f.default is not MISSING}

        # 저장 옵션
        self._cb_dual.setChecked(bool(d.get('save_dual_copy', False)))
        self._cb_subset.setChecked(bool(d.get('subset_fonts', True)))

        # 도구 기본 스타일 — 공장 기본값 스냅샷 사용
        from utils.annot_style import factory_tool_defaults
        factory = factory_tool_defaults()
        for name, (cur_color, btn) in self._tool_colors.items():
            fd = factory.get(name)
            if fd is None:
                continue
            self._tool_colors[name][0] = QColor(fd['color'])
            btn.setStyleSheet(f'background-color: {QColor(fd["color"]).name()};')
            if name in self._tool_opacities:
                self._tool_opacities[name].setValue(float(fd['opacity']))
            if name in self._tool_widths:
                self._tool_widths[name].setValue(float(fd['width']))

        # 블러
        idx = self._blur_mode_cb.findData(d.get('blur_mode', 'gaussian'))
        self._blur_mode_cb.setCurrentIndex(max(0, idx))
        self._blur_strength_sb.setValue(int(d.get('blur_strength', 12)))

        # 사전 옵션 (파일 경로는 유지 — 옆의 '해제' 버튼이 별도 역할)
        self._cb_dict.setChecked(bool(d.get('dict_enabled', False)))
        self._cb_online.setChecked(bool(d.get('dict_online_mode', False)))
        self._cb_dict_english_only.setChecked(bool(d.get('dict_english_only', False)))
        self._dict_popup_fs.setValue(int(d.get('dict_popup_font_size', 12)))
        self._on_online_mode_changed()

        # 책 보기
        self._apply_book_preset(str(d.get('book_preset', 'classic')))

    def _pick_tool_color(self, name: str):
        cur_color, btn = self._tool_colors[name]
        c = QColorDialog.getColor(cur_color, self)
        if c.isValid():
            self._tool_colors[name][0] = c
            btn.setStyleSheet(f'background-color: {c.name()};')

    def _pick_book_color(self):
        c = QColorDialog.getColor(self._book_color, self)
        if c.isValid():
            self._book_color = c
            self._book_color_btn.setStyleSheet(f'background-color: {c.name()};')
            self._book_color_lbl.setText(c.name())
            self._book_preset = 'custom'

    def _apply_book_preset(self, key: str):
        _label, color, strength = _BOOK_PRESETS[key]
        self._book_color = QColor(color)
        self._book_color_btn.setStyleSheet(f'background-color: {self._book_color.name()};')
        self._book_color_lbl.setText(self._book_color.name())
        self._book_texture_sb.setValue(int(strength))
        self._book_preset = key

    def _on_online_mode_changed(self, *_):
        """온라인 모드 체크박스 변경 시 로컬 사전 파일 영역 활성/비활성."""
        online = self._cb_online.isChecked()
        self._dict_file_widget.setEnabled(not online)
        self._dict_file_widget.setStyleSheet(
            'color: #aaa;' if online else ''
        )

    def _browse_dict(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '사전 파일 선택', '',
            '사전 파일 (*.mdic *.mdict *.mdx *.dict *.ifo *.tsv *.txt *.json);;모든 파일 (*)')
        if not path:
            return
        from utils.dict_manager import dict_manager
        ok, msg = dict_manager().load(path)
        if ok:
            self._dict_path_ed.setText(path)
            self._settings.dict_paths = [path]
            self._settings.dict_active_path = path
            dict_manager().enabled = self._cb_dict.isChecked()
        self._dict_status.setText(msg)
        self._dict_status.setStyleSheet(
            f'font-size: 11px; color: {"#2a7" if ok else "#c33"};')

    def _unload_dict(self):
        from utils.dict_manager import dict_manager
        dict_manager().unload()
        self._dict_path_ed.clear()
        self._settings.dict_paths = []
        self._settings.dict_path = ''
        self._settings.dict_active_path = ''
        self._dict_status.setText('사전 해제됨')
        self._dict_status.setStyleSheet('font-size: 11px; color: #666;')

    def _refresh_dict_status(self):
        from utils.dict_manager import dict_manager
        dm = dict_manager()
        if dm.is_loaded:
            self._dict_status.setText(f'로드됨: {dm.word_count:,}개 단어')
            self._dict_status.setStyleSheet('font-size: 11px; color: #2a7;')
        else:
            self._dict_status.setText('사전 미로드')
            self._dict_status.setStyleSheet('font-size: 11px; color: #888;')

    def _save_and_accept(self):
        self._settings.save_dual_copy = self._cb_dual.isChecked()
        self._settings.subset_fonts = self._cb_subset.isChecked()
        tool_defaults: dict = {}
        for name, (color, _btn) in self._tool_colors.items():
            vals: dict = {'color': color.name()}
            if name in self._tool_opacities:
                vals['opacity'] = self._tool_opacities[name].value()
            if name in self._tool_widths:
                vals['width'] = self._tool_widths[name].value()
            tool_defaults[name] = vals
        self._settings.tool_defaults = tool_defaults
        apply_settings_defaults(tool_defaults)
        self._settings.dict_enabled = self._cb_dict.isChecked()
        self._settings.dict_online_mode = self._cb_online.isChecked()
        self._settings.dict_english_only = self._cb_dict_english_only.isChecked()
        self._settings.dict_path = self._dict_path_ed.text()
        if not getattr(self._settings, 'dict_paths', None):
            self._settings.dict_paths = [self._settings.dict_path] if self._settings.dict_path else []
        if self._settings.dict_paths:
            self._settings.dict_path = self._settings.dict_paths[0]
        if getattr(self._settings, 'dict_active_path', '') and self._settings.dict_active_path not in self._settings.dict_paths:
            self._settings.dict_active_path = self._settings.dict_paths[0] if self._settings.dict_paths else ''
        self._settings.dict_popup_font_size = self._dict_popup_fs.value()
        self._settings.blur_mode = str(self._blur_mode_cb.currentData() or 'gaussian')
        self._settings.blur_strength = int(self._blur_strength_sb.value())
        self._settings.book_bg_color = self._book_color.name()
        self._settings.book_texture_strength = self._book_texture_sb.value()
        self._settings.book_preset = getattr(self, '_book_preset', 'classic')
        from utils.dict_manager import dict_manager
        dict_manager().enabled = self._settings.dict_enabled
        self._settings.save()
        self.accept()
