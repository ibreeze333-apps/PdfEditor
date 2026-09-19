# ui/toolbar.py — 어노테이션 툴바
# 색/굵기는 각 도구 아이콘 우클릭 메뉴에서 개별 설정·기억됨
from __future__ import annotations
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QToolBar, QLabel, QColorDialog, QMenu, QInputDialog,
    QWidgetAction, QWidget, QHBoxLayout, QSlider,
)
from ui.glass_button import GlassButton
from ui.flow_bar import FlowBar

from tools.select_tool        import SelectTool
from tools.highlight_tool     import HighlightTool
from tools.underline_tool     import UnderlineTool
from tools.strikethrough_tool import StrikethroughTool
from tools.pencil_tool        import PencilTool
from tools.text_tool          import TextTool
from tools.note_tool          import NoteTool
from tools.index_tab_tool     import IndexTabTool
from tools.arrow_tool         import ArrowTool, LineTool, DoubleArrowTool
from tools.block_arrow_tool   import BlockArrowTool
from tools.shape_tool         import ShapeTool
from tools.stamp_tool         import StampTool
from tools.image_tool         import ImageTool
from tools.mosaic_tool        import MosaicTool, BlurTool
from utils.annot_style        import (tool_style, DASH_PRESETS,
                                      STROKE_WIDTH_OPTIONS, PRESET_TOOLS,
                                      get_presets, apply_preset,
                                      add_user_preset, delete_user_preset,
                                      is_user_preset)


# 도구별 유리 색조 — 도구 성격이 색으로도 드러나게 한다(형광펜=분홍, 블러=하늘…).
_TOOL_ACCENTS = {
    'select':        '#8fa7d8',
    'highlight':     '#f0919f',
    'underline':     '#a99ae0',
    'strikethrough': '#a8adb8',
    'pencil':        '#e5a76a',
    'line':          '#8fa0b4',
    'arrow':         '#7f93cf',
    'shape':         '#9b8ede',
    'stamp':         '#8d93a3',
    'image':         '#7fbf95',
    'mosaic':        '#9ec46f',
    'blur':          '#79b6dd',
    'text':          '#9aa3b2',
    'note':          '#e8c46a',
    'index_tab':     '#e0899f',
    'double_arrow':  '#7f93cf',
    'block_arrow':   '#7f93cf',
}

_TOOL_DEFS = [
    ('select',        '🖱 선택',     SelectTool),
    ('highlight',     '🖌 형광펜',   HighlightTool),
    ('underline',     '📏 밑줄',     UnderlineTool),
    ('strikethrough', '~~취소선~~',  StrikethroughTool),
    ('pencil',        '✏ 연필',      PencilTool),
    ('line',          '➖ 직선',     LineTool),
    ('arrow',         '➡ 화살표',   ArrowTool),
    ('shape',         '⬛ 도형',     ShapeTool),
    ('stamp',         '🔖 스탬프',  StampTool),
    ('image',         '🖼 이미지',   ImageTool),
    ('mosaic',        '\U0001F58D \ub9c8\ucee4', MosaicTool),
    ('blur',          '💧 블러',    BlurTool),
    ('text',          '🔤 텍스트',   TextTool),
    ('note',          '📌 메모',     NoteTool),
    ('index_tab',     '🔖 인덱스',   IndexTabTool),
]


class AnnotToolBar(QToolBar):
    note_panel_requested = Signal()
    dict_requested = Signal()

    def __init__(self, canvas, parent=None):
        super().__init__('어노테이션 도구', parent)
        self._canvas = canvas
        self._group  = QActionGroup(self)
        self._group.setExclusive(True)
        self._tools: dict[str, object] = {}
        self._active_arrow_name: str = 'arrow'
        self._arrow_action: QAction | None = None
        self.setMovable(False)
        self.setFloatable(False)
        self.setStyleSheet('QToolBar::separator { width: 4px; margin: 0 4px; background: transparent; }')

        self._glass_btns: list[GlassButton] = []

        # 버튼을 QToolBar 에 바로 넣지 않고 줄바꿈 컨테이너에 담는다 —
        # 고DPI/좁은 창에서 오른쪽 버튼이 잘려 사라지지 않게 (ui/flow_bar.py)
        self._flow = FlowBar(self)
        _flow_action = QWidgetAction(self)
        _flow_action.setDefaultWidget(self._flow)
        self.addAction(_flow_action)

        # ── 도구 버튼 (GlassButton + QWidgetAction) ────────────────
        text_action_inserted = False
        for name, label, cls in _TOOL_DEFS:
            tool = cls()
            self._tools[name] = tool

            # 텍스트 도구 앞에 구분선
            if name == 'text' and not text_action_inserted:
                self._flow.add_separator()
                text_action_inserted = True

            btn = GlassButton(label)
            btn.setCheckable(True)
            btn.setMinimumWidth(52)
            btn.setObjectName(name)
            btn.set_accent(_TOOL_ACCENTS.get(name, '#8fa7d8'))
            if name == 'select':
                btn.setShortcut(QKeySequence('V'))
                btn.setToolTip(f'{label}  [V]')

            # 클릭 핸들러
            # 토글 방식: 이미 켜진 도구 버튼을 다시 누르면 '선택' 도구로 복귀.
            # ('선택' 버튼 자신은 항상 켜진 상태 유지 — 끌 대상이 없음)
            if name == 'stamp':
                btn.clicked.connect(
                    lambda checked, t=tool, b=btn:
                        self._activate_stamp_btn(t, b) if checked
                        else self._select_tool_fallback())
            elif name == 'arrow':
                self._tools['double_arrow'] = DoubleArrowTool()
                self._tools['block_arrow']  = BlockArrowTool()
                self._arrow_btn = btn
                btn.clicked.connect(
                    lambda checked, b=btn:
                        self._activate_arrow_btn(b) if checked
                        else self._select_tool_fallback())
            elif name == 'select':
                btn.clicked.connect(
                    lambda checked, t=tool, b=btn:
                        self._on_glass_btn_clicked(b, t) if checked else b.setChecked(True))
            else:
                btn.clicked.connect(
                    lambda checked, t=tool, b=btn:
                        self._on_glass_btn_clicked(b, t) if checked
                        else self._select_tool_fallback())

            # 우클릭 → 도구별 스타일 메뉴 (인덱스는 색/선굵기가 의미 없어 제외)
            if name != 'index_tab':
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                if name == 'arrow':
                    btn.customContextMenuRequested.connect(
                        lambda p, b=btn:
                            self._show_tool_ctx(self._active_arrow_name, b.mapToGlobal(p)))
                else:
                    btn.customContextMenuRequested.connect(
                        lambda p, n=name, b=btn:
                            self._show_tool_ctx(n, b.mapToGlobal(p)))

            self._flow.add_widget(btn)
            self._glass_btns.append(btn)

        # 첫 번째(선택) 버튼 활성화
        if self._glass_btns:
            self._glass_btns[0].setChecked(True)

    def set_tools_enabled(self, on: bool):
        """도구 버튼만 켜고 끈다 (툴바 전체를 disable 하면 같은 줄에 얹은
        저장·본문인식 버튼까지 함께 잠겨 버린다)."""
        for b in self._glass_btns:
            b.setEnabled(on)

    def add_trailing_widget(self, widget, separator: bool = False):
        """도구 버튼 뒤에 다른 버튼(저장·본문인식 등)을 이어 붙인다.

        같은 줄바꿈 컨테이너에 들어가므로, 폭이 모자라면 잘리지 않고
        다음 줄로 내려간다."""
        if separator:
            self._flow.add_separator()
        self._flow.add_widget(widget)
        return widget

    # ── 스탬프 활성화 팝업 ──────────────────────────────────────────
    def _activate_stamp(self, tool, action):
        """스탬프 툴바 버튼 클릭 시: 스탬프 종류 팝업 → 모드 설정 후 활성화."""
        from tools.stamp_tool import (
            STAMP_KR, STAMP_NAMES, DATE_STAMP_LABEL, DATE_STAMP_NAME, SYMBOL_STAMPS,
            CHARACTER_STAMPS, format_stamp_label,
        )
        from ui.dialogs.stamp_manager_dialog import load_custom_stamps, _SHAPE_LABELS
        from PySide6.QtWidgets import QMenu

        def _set_stamp(name):
            tool._circle_mode = False
            tool.stamp_name   = name
            self._canvas.set_tool(tool)

        menu = QMenu(self)
        menu.setTitle('스탬프 선택')

        # ── 색상/투명도 설정 ─────────────────────────────────────
        opacity_pct = int(tool._stamp_opacity * 100)
        color_tag   = f'  색: {tool._stamp_color_override}' if tool._stamp_color_override else ''
        menu.addAction(f'🎚 투명도: {opacity_pct}%{color_tag}').setEnabled(False)
        act_settings = menu.addAction('⚙ 색상 / 투명도 설정…')
        def _open_stamp_settings(checked=False):
            from tools.stamp_tool import StampSettingsDialog
            dlg = StampSettingsDialog(tool, self)
            if dlg.exec():
                tool._stamp_opacity       = dlg._get_opacity()
                tool._stamp_color_override = dlg._get_color()
        act_settings.triggered.connect(_open_stamp_settings)
        menu.addSeparator()

        # ── 커스텀 도장 스탬프 ───────────────────────────────────
        customs = load_custom_stamps()
        if customs:
            menu.addAction('─── 커스텀 도장 스탬프 ───').setEnabled(False)
            for cs in customs:
                if cs.get('type') == 'image':
                    icon = '📷'
                    sub  = ''
                else:
                    shape = cs.get('shape', 'rect')
                    icon  = '🖋'
                    sub   = f"  [{_SHAPE_LABELS.get(shape, shape)}]"
                a = menu.addAction(f'{icon} {cs["name"]}{sub}')
                def _pick_custom(checked=False, _cs=cs):
                    _set_stamp(_cs['name'])
                a.triggered.connect(_pick_custom)
            menu.addSeparator()

        act_mgr = menu.addAction('⚙ 커스텀 스탬프 만들기 / 관리…')
        def _open_manager(checked=False):
            from ui.dialogs.stamp_manager_dialog import StampManagerDialog
            StampManagerDialog(self).exec()
        act_mgr.triggered.connect(_open_manager)

        menu.addSeparator()

        # 캐릭터 도장 하위 메뉴 ──────────────────────────────
        char_menu = menu.addMenu('\uce90\ub9ad\ud130 \ub3c4\uc7a5 \u25b6')
        for cs in CHARACTER_STAMPS:
            a = char_menu.addAction(cs['label'])
            def _pick_char(checked=False, _id=cs['id']):
                _set_stamp(_id)
            a.triggered.connect(_pick_char)

        menu.addSeparator()

        # ── 기존 스탬프 (하위메뉴) ───────────────────────────────
        legacy = menu.addMenu('기존 스탬프 ▶')

        legacy.addAction('─── 한국어 스탬프 ───').setEnabled(False)
        for kr in STAMP_KR:
            a = legacy.addAction(kr)
            def _pick_kr(checked=False, k=kr):
                _set_stamp(STAMP_KR[k])
            a.triggered.connect(_pick_kr)

        legacy.addSeparator()
        legacy.addAction('─── 영문 스탬프 ───').setEnabled(False)
        for en in STAMP_NAMES:
            a = legacy.addAction(format_stamp_label(en))
            def _pick_en(checked=False, e=en):
                _set_stamp(e)
            a.triggered.connect(_pick_en)

        legacy.addSeparator()
        legacy.addAction('─── 날짜 스탬프 ───').setEnabled(False)
        act_date = legacy.addAction(f'📅  {DATE_STAMP_LABEL}')
        act_date.triggered.connect(lambda: _set_stamp(DATE_STAMP_NAME))

        legacy.addSeparator()
        legacy.addAction('─── 심볼 스탬프 ───').setEnabled(False)
        for sym in SYMBOL_STAMPS:
            a = legacy.addAction(f"{sym['text']}  {sym['label']}")
            def _pick_symbol(checked=False, _sym=sym):
                _set_stamp(_sym['id'])
            a.triggered.connect(_pick_symbol)

        menu.addSeparator()

        # ── 원번호 모드 ──────────────────────────────────────────
        if tool._circle_mode:
            lbl = menu.addAction(
                f'① 원번호 모드 켜짐  (다음: {tool._circle_counter}번)')
            lbl.setEnabled(False)
            menu.addAction('↺  1번부터 다시').triggered.connect(
                lambda: tool.reset_circle_counter(1))
            act_set = menu.addAction('✎  시작 번호 지정…')
            def _set_n(checked=False):
                n, ok = QInputDialog.getInt(
                    self, '원번호 시작', '시작 번호:',
                    tool._circle_counter, 1, 9999)
                if ok:
                    tool.reset_circle_counter(n)
                    self._canvas.set_tool(tool)
            act_set.triggered.connect(_set_n)
            menu.addSeparator()
            menu.addAction('✕  원번호 모드 끄기').triggered.connect(
                lambda: (tool.exit_circle_mode(), self._canvas.set_tool(tool)))
            menu.addSeparator()
            act_circle = menu.addAction('① 원번호 계속 사용')
        else:
            act_circle = menu.addAction('① 원번호 모드로 시작')
        act_circle.triggered.connect(
            lambda: (setattr(tool, '_circle_mode', True),
                     self._canvas.set_tool(tool)))

        # 버튼 위치에서 팝업 표시
        stamp_btn = next((b for b in self._glass_btns if b.objectName() == 'stamp'), None)
        gpos = stamp_btn.mapToGlobal(stamp_btn.rect().bottomLeft()) if stamp_btn else \
               self.mapToGlobal(self.rect().bottomLeft())
        result = menu.exec(gpos)

        # 아무것도 선택 안 했으면 이전 도구 버튼 복원
        if result is None:
            self._restore_active_btn()

    # ── GlassButton 공통 helpers ─────────────────────────────────────
    def _on_glass_btn_clicked(self, clicked_btn, tool):
        """GlassButton exclusive 선택 처리 후 도구 활성화."""
        for btn in self._glass_btns:
            if btn is not clicked_btn:
                btn.setChecked(False)
        self._canvas.set_tool(tool)

    def _select_tool_fallback(self):
        """활성 도구를 끄고 기본 '선택' 도구로 돌아간다 (토글 off)."""
        sel = self._tools.get('select')
        for btn in self._glass_btns:
            btn.setChecked(btn.objectName() == 'select')
        if sel is not None and self._canvas is not None:
            self._canvas.set_tool(sel)

    def set_canvas(self, canvas):
        """탭 전환 시 캔버스를 교체한다."""
        self._canvas = canvas
        self._restore_active_btn()

    def _restore_active_btn(self):
        """현재 캔버스 도구에 맞는 버튼 복원."""
        cur = self._canvas.current_tool()
        for btn in self._glass_btns:
            t = self._tools.get(btn.objectName())
            btn.setChecked(t is cur)

    def _activate_stamp_btn(self, tool, btn: 'GlassButton'):
        """스탬프 GlassButton 클릭 시: 팝업 메뉴 표시 후 처리."""
        self._on_glass_btn_clicked(btn, tool)
        self._activate_stamp(tool, None)

    def _activate_arrow_btn(self, btn: 'GlassButton'):
        """화살표 GlassButton 클릭 시: 마지막 선택 종류 바로 활성화."""
        self._on_glass_btn_clicked(btn, self._tools.get(self._active_arrow_name)
                                   or self._tools.get('arrow'))

    # ── 직선/화살표 그룹 활성화 ──────────────────────────────────────
    _ARROW_LABELS = {
        'arrow':        '➡ 화살표',
        'double_arrow': '↔ 양방향 화살표',
        'block_arrow':  '🔶 블록 화살표',
    }

    def _activate_arrow(self, action):
        """(레거시) 화살표 버튼 클릭 시: 마지막 선택 종류 바로 활성화."""
        t = self._tools.get(self._active_arrow_name) or self._tools.get('arrow')
        if t:
            self._canvas.set_tool(t)

    def _set_arrow_type(self, name: str):
        """화살표 그룹에서 종류 선택 → 버튼 레이블 갱신 + 도구 활성화."""
        self._active_arrow_name = name
        if hasattr(self, '_arrow_btn') and self._arrow_btn:
            self._arrow_btn.setText(self._ARROW_LABELS.get(name, '➡ 화살표'))
            self._on_glass_btn_clicked(self._arrow_btn,
                                       self._tools.get(name) or self._tools.get('arrow'))
        t = self._tools.get(name)
        if t:
            self._canvas.set_tool(t)

    # ── 도형 종류 ────────────────────────────────────────────────────
    def _on_shape_changed(self, text: str):
        m = {'\uc0ac\uac01\ud615': 'rect', '\uc6d0': 'circle', '\uc0bc\uac01\ud615': 'triangle', '\uc624\uac01\ud615': 'pentagon', '\uc721\uac01\ud615': 'hexagon'}
        t = self._tools.get('shape')
        if t:
            t.shape_type = m.get(text, 'rect')

    def _add_width_slider(self, menu, st):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(5, 120)
        slider.setSingleStep(1)
        slider.setValue(int(round(st.width * 10)))
        value_lbl = QLabel(f'{st.width:.1f}pt')
        value_lbl.setMinimumWidth(48)
        row = QWidget(menu)
        ly = QHBoxLayout(row)
        ly.setContentsMargins(8, 4, 8, 4)
        ly.addWidget(QLabel('\uad75\uae30'))
        ly.addWidget(slider, 1)
        ly.addWidget(value_lbl)
        slider.valueChanged.connect(lambda v: (setattr(st, 'width', v / 10.0), value_lbl.setText(f'{v / 10.0:.1f}pt')))
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)

    def _show_tool_ctx(self, tool_name: str, global_pos: QPoint):
        """Show a per-tool context menu for annotation settings."""
        st = tool_style(tool_name)
        tool = self._tools.get(tool_name)
        menu = QMenu(self)

        # 화살표 그룹: 종류 선택 서브메뉴를 맨 위에 표시
        _ARROW_GROUP = ('arrow', 'double_arrow', 'block_arrow')
        if tool_name in _ARROW_GROUP:
            _ARROW_SUBS = [
                ('arrow',        '➡  화살표'),
                ('double_arrow', '↔  양방향 화살표'),
                ('block_arrow',  '🔶  블록 화살표'),
            ]
            type_menu = menu.addMenu('종류')
            for sub_name, sub_label in _ARROW_SUBS:
                a = type_menu.addAction(sub_label)
                a.setCheckable(True)
                a.setChecked(sub_name == tool_name)
                a.triggered.connect(
                    lambda checked=False, n=sub_name: self._set_arrow_type(n))
            menu.addSeparator()

        if tool_name in PRESET_TOOLS:
            presets = get_presets(tool_name)
            if presets:
                pm = menu.addMenu('\u2b50 \ud504\ub9ac\uc14b')
                for preset in presets:
                    action = pm.addAction(preset['name'])
                    if is_user_preset(tool_name, preset['name']):
                        action.setText(preset['name'] + '  \u270e')

                    def _apply_p(checked=False, _p=preset, _n=tool_name, _tool=tool):
                        apply_preset(_n, _p)
                        if _n == 'shape' and _tool is not None:
                            if 'fill_mode' in _p:
                                _tool.fill_mode = _p['fill_mode']
                            if 'fill_color' in _p:
                                _tool.fill_color = QColor(_p['fill_color'])
                        if _n in ('arrow', 'double_arrow', 'block_arrow'):
                            self._set_arrow_type(_n)
                        else:
                            for act in self._group.actions():
                                if act.objectName() == _n:
                                    act.setChecked(True)
                                    self._canvas.set_tool(self._tools[_n])
                                    break

                    action.triggered.connect(_apply_p)

                pm.addSeparator()
                act_save_p = pm.addAction('\ud604\uc7ac \uc124\uc815\uc73c\ub85c \uc800\uc7a5\u2026')

                def _save_preset(checked=False, _n=tool_name, _tool=tool):
                    name, ok = QInputDialog.getText(self, '\ud504\ub9ac\uc14b \uc800\uc7a5', '\ud504\ub9ac\uc14b \uc774\ub984\uc744 \uc785\ub825\ud558\uc138\uc694:')
                    if not ok or not name.strip():
                        return
                    cur_style = tool_style(_n)
                    preset = {'name': name.strip(), 'color': cur_style.color.name()}
                    if _n == 'highlight':
                        preset['opacity'] = cur_style.opacity
                        preset['width'] = cur_style.width
                    else:
                        preset['width'] = cur_style.width
                        preset['dash'] = cur_style.dash_name
                    if _n in ('arrow', 'double_arrow'):
                        preset['arrow_head'] = getattr(cur_style, 'arrow_head', 'closed')
                        preset['arrow_fill'] = getattr(cur_style, 'arrow_fill', 'filled')
                    if _n == 'shape' and _tool is not None:
                        preset['fill_mode'] = getattr(_tool, 'fill_mode', 'none')
                        fill_color = getattr(_tool, 'fill_color', None)
                        if fill_color is not None:
                            preset['fill_color'] = fill_color.name()
                    add_user_preset(_n, preset)

                act_save_p.triggered.connect(_save_preset)
                act_del_p = pm.addAction('\uc0ac\uc6a9\uc790 \ud504\ub9ac\uc14b \uc0ad\uc81c\u2026')

                def _del_preset(checked=False, _n=tool_name):
                    user_presets = [p for p in get_presets(_n) if is_user_preset(_n, p['name'])]
                    if not user_presets:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(self, '\uc0ad\uc81c', '\uc0ad\uc81c\ud560 \uc0ac\uc6a9\uc790 \ud504\ub9ac\uc14b\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.')
                        return
                    names = [p['name'] for p in user_presets]
                    name, ok = QInputDialog.getItem(self, '\ud504\ub9ac\uc14b \uc0ad\uc81c', '\uc0ad\uc81c\ud560 \ud504\ub9ac\uc14b \uc120\ud0dd:', names, 0, False)
                    if ok and name:
                        delete_user_preset(_n, name)

                act_del_p.triggered.connect(_del_preset)
            menu.addSeparator()

        if tool_name == 'mosaic':
            marker_menu = menu.addMenu('\ub9c8\ucee4 \uc0c9\uc0c1')
            marker_colors = [
                ('\uac80\uc815', '#000000'),
                ('\ud770\uc0c9', '#ffffff'),
                ('\ube68\uac15', '#ff0000'),
                ('\ud30c\ub791', '#0066ff'),
                ('\ub178\ub791', '#ffd400'),
            ]
            for label, value in marker_colors:
                action = marker_menu.addAction(f'{label}  {value}')
                action.setCheckable(True)
                action.setChecked(st.color.name().lower() == value.lower())
                action.triggered.connect(lambda checked, v=value, _st=st: setattr(_st, 'color', QColor(v)))
        elif tool_name not in ('select', 'stamp', 'image', 'blur'):
            act_color = menu.addAction(f'\uc0c9\uc0c1  {st.color.name()}')

            def _pick(checked=False, _st=st):
                dlg = QColorDialog(_st.color, self)
                dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                if dlg.exec():
                    _st.color = dlg.selectedColor()

            act_color.triggered.connect(_pick)

        if tool_name == 'blur' and tool is not None:
            blur_mode_menu = menu.addMenu('\ube14\ub7ec \ubc29\uc2dd')
            blur_modes = [
                ('\uac15\ud55c \ube14\ub7ec', 'gaussian'),
                ('\ud53d\uc140\ud654', 'pixelate'),
                ('\ub178\uc774\uc988 \uc11e\uae30', 'noise'),
                ('\ucd95\uc18c \ud6c4 \uc7ac\ud655\ub300', 'downscale'),
            ]
            for label, value in blur_modes:
                action = blur_mode_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(getattr(tool, 'blur_mode', 'gaussian') == value)
                def _set_blur_mode(checked=False, v=value, t=tool, canvas=self._canvas):
                    t.blur_mode = v
                    settings = getattr(canvas, '_settings', None)
                    if settings is not None:
                        settings.blur_mode = v
                        settings.blur_strength = int(getattr(t, 'blur_radius', 12))
                action.triggered.connect(_set_blur_mode)

            strength_menu = menu.addMenu('\uac15\ub3c4')
            for label, value in [('\ubcf4\ud1b5  8', 8), ('\uac15\ud558\uac8c  12', 12), ('\ub9e4\uc6b0 \uac15\ud558\uac8c  18', 18), ('\uadf9\uac15  26', 26), ('\ucd5c\uac15  36', 36)]:
                action = strength_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(int(getattr(tool, 'blur_radius', 12)) == value)
                def _set_blur_strength(checked=False, v=value, t=tool, canvas=self._canvas):
                    t.blur_radius = v
                    settings = getattr(canvas, '_settings', None)
                    if settings is not None:
                        settings.blur_mode = getattr(t, 'blur_mode', 'gaussian')
                        settings.blur_strength = int(v)
                action.triggered.connect(_set_blur_strength)
            strength_menu.addSeparator()
            custom_strength = strength_menu.addAction('\uc9c1\uc811 \uc785\ub825\u2026')
            custom_strength.triggered.connect(
                lambda checked=False, t=tool, canvas=self._canvas, parent=menu: (
                    lambda n, ok: (
                        setattr(t, 'blur_radius', int(n)),
                        setattr(getattr(canvas, '_settings', None), 'blur_mode', getattr(t, 'blur_mode', 'gaussian')) if getattr(canvas, '_settings', None) is not None else None,
                        setattr(getattr(canvas, '_settings', None), 'blur_strength', int(n)) if getattr(canvas, '_settings', None) is not None else None
                    ) if ok else None
                )(*QInputDialog.getInt(parent, '\ube14\ub7ec \uac15\ub3c4', '\uac15\ub3c4:', int(getattr(t, 'blur_radius', 12)), 6, 60, 1))
            )

        if tool_name not in ('note', 'stamp', 'image', 'select', 'text', 'mosaic', 'blur'):
            menu.addSeparator()
            width_menu = menu.addMenu('\uc120 \uad75\uae30')
            for val in STROKE_WIDTH_OPTIONS:
                label = f'{val:.1f}pt' if val % 1 else f'{int(val)}pt'
                action = width_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(st.width - val) < 0.05)
                action.triggered.connect(lambda checked, v=val, _st=st: setattr(_st, 'width', v))
            width_menu.addSeparator()
            custom_width = width_menu.addAction('\uc9c1\uc811 \uc785\ub825\u2026')
            custom_width.triggered.connect(
                lambda checked=False, _st=st, parent=width_menu: (
                    lambda n, ok: setattr(_st, 'width', float(n)) if ok else None
                )(*QInputDialog.getDouble(parent, '\uc120 \uad75\uae30', '\uad75\uae30 (pt):', float(_st.width), 0.5, 12.0, 1))
            )
            self._add_width_slider(width_menu, st)

        if tool_name in ('underline', 'strikethrough', 'pencil', 'line', 'arrow', 'double_arrow', 'shape'):
            style_menu = menu.addMenu('\uc120 \uc2a4\ud0c0\uc77c')
            dash_keys = list(DASH_PRESETS.keys())
            _exclude = {'\ubb3c\uacb0\ubb34\ub2ac', '\uac15\uc870\uc120'}
            if tool_name == 'shape':
                dash_keys = [n for n in dash_keys if n not in _exclude]
            elif tool_name == 'pencil':
                dash_keys = [n for n in dash_keys if n not in _exclude]
            for dash_name in dash_keys:
                action = style_menu.addAction(dash_name)
                action.setCheckable(True)
                action.setChecked(st.dash_name == dash_name)
                action.triggered.connect(lambda checked, n=dash_name, _st=st: _st.set_dash(n))

        if tool_name in ('arrow', 'double_arrow'):
            arrow_menu = menu.addMenu('\ud654\uc0b4\ud45c \uba38\ub9ac')
            mode_items = [
                ('\uc5f4\ub9b0 \ud654\uc0b4\ud45c', 'open', 'hollow', False),
                ('\ub2eb\ud78c \ud654\uc0b4\ud45c', 'closed', 'filled', False),
                ('\ube48 \ub2eb\ud78c \ud654\uc0b4\ud45c', 'closed', 'hollow', False),
                ('\uc0bc\uac01 \ud654\uc0b4\ud45c', 'closed', 'filled', True),
            ]
            if tool_name == 'double_arrow':
                mode_items[-1] = ('\uc0bc\uac01 \uc591\ubc29\ud5a5 \ud654\uc0b4\ud45c', 'closed', 'filled', True)
            for label, head, fill, emphasized in mode_items:
                action = arrow_menu.addAction(label)
                action.setCheckable(True)
                current_emphasized = getattr(st, 'dash_name', '') == '\uac15\uc870\uc120'
                action.setChecked(
                    getattr(st, 'arrow_head', 'closed') == head
                    and getattr(st, 'arrow_fill', 'filled') == fill
                    and current_emphasized == emphasized
                )
                action.triggered.connect(
                    lambda checked, h=head, f=fill, em=emphasized, _st=st: (
                        setattr(_st, 'arrow_head', h),
                        setattr(_st, 'arrow_fill', f),
                        _st.set_dash('\uac15\uc870\uc120' if em else '\uc2e4\uc120'),
                    )
                )

        if tool_name == 'highlight':
            menu.addSeparator()
            opacity_menu = menu.addMenu('\ubd88\ud22c\uba85\ub3c4')
            for label, value in [('\uc5f0\ud558\uac8c  20%', 0.2), ('\ubcf4\ud1b5  40%', 0.4), ('\uc9c4\ud558\uac8c  60%', 0.6), ('\uc544\uc8fc \uc9c4\ud558\uac8c  80%', 0.8)]:
                action = opacity_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(abs(st.opacity - value) < 0.05)
                action.triggered.connect(lambda checked, v=value, _st=st: setattr(_st, 'opacity', v))

            if tool:
                menu.addSeparator()
                lock_action = menu.addAction('\ud615\uad11\ud39c \ub192\uc774 \uace0\uc815')
                lock_action.setCheckable(True)
                lock_action.setChecked(getattr(tool, '_fixed_height_enabled', False))
                lock_action.triggered.connect(lambda checked, t=tool: t.set_fixed_height_enabled(checked))
                update_action = menu.addAction('\ucd5c\uadfc \ub192\uc774\ub85c \uace0\uc815\uac12 \uac31\uc2e0')
                update_action.triggered.connect(
                    lambda checked=False, t=tool: setattr(t, '_fixed_height_pts', max(2.0, float(getattr(t, '_last_height_pts', 12.0))))
                )

        if tool_name == 'text' and tool:
            menu.addSeparator()
            cur = getattr(tool, '_font_size', 12)
            font_menu = menu.addMenu('\uae00\uc790 \ud06c\uae30')
            for label, value in [('\uc791\uac8c  8pt', 8), ('\ubcf4\ud1b5  12pt', 12), ('\ud06c\uac8c  16pt', 16), ('\uc544\uc8fc \ud06c\uac8c  24pt', 24)]:
                action = font_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(cur == value)
                action.triggered.connect(lambda checked, v=value, t=tool: setattr(t, '_font_size', v))
            font_menu.addSeparator()
            custom_action = font_menu.addAction('\uc9c1\uc811 \uc785\ub825\u2026')
            custom_action.triggered.connect(
                lambda checked=False, t=tool, parent=menu: (
                    lambda n, ok: setattr(t, '_font_size', n) if ok else None
                )(*QInputDialog.getInt(parent, '\ud14d\uc2a4\ud2b8 \ud06c\uae30', '\uae30\ubcf8 \uae00\uc790 \ud06c\uae30 (pt):', int(getattr(t, '_font_size', 12)), 4, 300, 1))
            )
            font_action = menu.addAction('\uae00\uaf34 \uc120\ud0dd\u2026')
            font_action.triggered.connect(
                lambda checked=False, t=tool, parent=menu: t.configure_style(parent) if hasattr(t, 'configure_style') else None
            )

        if tool_name == 'pencil' and tool:
            menu.addSeparator()
            is_eraser = getattr(tool, '_eraser_mode', False)
            eraser_action = menu.addAction('\uc9c0\uc6b0\uac1c \ubaa8\ub4dc \ucf1c\uc9d0 (\ud604\uc7ac)' if is_eraser else '\uc9c0\uc6b0\uac1c \ubaa8\ub4dc')
            eraser_action.setCheckable(True)
            eraser_action.setChecked(is_eraser)
            eraser_action.triggered.connect(lambda checked, t=tool: setattr(t, 'eraser_mode', checked))

        if tool_name == 'stamp' and tool:
            menu.addSeparator()
            is_circle = getattr(tool, '_circle_mode', False)
            counter = getattr(tool, '_circle_counter', 1)
            if is_circle:
                menu.addAction(f'\u2460 \uc6d0\ubc88\ud638 \ubaa8\ub4dc \ucf1c\uc9d0  (\ub2e4\uc74c: {counter}\ubc88)').setEnabled(False)
                act_reset = menu.addAction('\u21ba  1\ubc88\ubd80\ud130 \ub2e4\uc2dc')
                act_reset.triggered.connect(lambda: tool.reset_circle_counter(1))
                act_set = menu.addAction('\uc2dc\uc791 \ubc88\ud638 \uc9c0\uc815\u2026')

                def _set_start(checked=False, _t=tool):
                    n, ok = QInputDialog.getInt(None, '\uc6d0\ubc88\ud638 \uc2dc\uc791', '\uc2dc\uc791 \ubc88\ud638:', _t._circle_counter, 1, 9999)
                    if ok:
                        _t.reset_circle_counter(n)

                act_set.triggered.connect(_set_start)
                menu.addSeparator()
                act_exit = menu.addAction('\uc6d0\ubc88\ud638 \ubaa8\ub4dc \ub044\uae30  (ESC)')
                act_exit.triggered.connect(lambda: tool.exit_circle_mode())
            else:
                act_enter = menu.addAction('\u2460 \uc6d0\ubc88\ud638 \ubaa8\ub4dc \ucf1c\uae30')
                act_enter.triggered.connect(lambda: setattr(tool, '_circle_mode', True))

        if tool_name == 'shape' and tool:
            menu.addSeparator()
            cur = getattr(tool, 'shape_type', 'rect')
            shape_menu = menu.addMenu('\ub3c4\ud615 \uc885\ub958')
            for label, value, combo_text in [('\u2b1b \uc0ac\uac01\ud615', 'rect', '\uc0ac\uac01\ud615'), ('\u2b24 \uc6d0', 'circle', '\uc6d0'), ('\u25b2 \uc0bc\uac01\ud615', 'triangle', '\uc0bc\uac01\ud615')]:
                action = shape_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(cur == value)
                action.triggered.connect(lambda checked, c=combo_text: self._on_shape_changed(c))

            menu.addSeparator()
            fill_mode = getattr(tool, 'fill_mode', 'none')
            fill_menu = menu.addMenu('\ucc44\uc6b0\uae30')
            for label, value in [('\uc18d \ube48 (\ud22c\uba85)', 'none'), ('\ud770\uc0c9 \ucc44\uc6b0\uae30', 'white'), ('\uc120 \uc0c9\uc73c\ub85c \ucc44\uc6b0\uae30', 'color')]:
                action = fill_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(fill_mode == value)
                action.triggered.connect(lambda checked, v=value, t=tool: setattr(t, 'fill_mode', v))

            fill_color = getattr(tool, 'fill_color', None) or st.color
            fill_action = menu.addAction(f'\ucc44\uc6b0\uae30 \uc0c9  {fill_color.name()}')

            def _pick_fill(checked=False, _t=tool):
                current = getattr(_t, 'fill_color', None) or tool_style('shape').color
                dlg = QColorDialog(current, self)
                dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
                if dlg.exec():
                    _t.fill_color = dlg.selectedColor()

            fill_action.triggered.connect(_pick_fill)

        menu.exec(global_pos)

    def tool_items(self) -> list[tuple[str, object]]:
        """(label, tool_instance) 리스트 반환 — 컨텍스트 메뉴용."""
        result = []
        for name, label, _ in _TOOL_DEFS:
            if name not in self._tools:
                continue
            tool = self._tools[name]
            if name == 'arrow':
                active = self._active_arrow_name
                result.append((self._ARROW_LABELS.get(active, label), self._tools[active]))
            elif name == 'stamp':
                result.append((self._stamp_current_label(tool, label), tool))
            elif name == 'shape':
                result.append((self._shape_current_label(tool, label), tool))
            else:
                result.append((label, tool))
        return result

    def _stamp_current_label(self, tool, fallback: str) -> str:
        try:
            from tools.stamp_tool import (STAMP_KR, DATE_STAMP_NAME, DATE_STAMP_LABEL,
                                          SYMBOL_STAMP_MAP, format_stamp_label)
        except ImportError:
            return fallback
        sname = getattr(tool, 'stamp_name', '')
        if not sname:
            return fallback
        if sname == DATE_STAMP_NAME:
            return f'🔖 {DATE_STAMP_LABEL}'
        sym = SYMBOL_STAMP_MAP.get(sname)
        if sym:
            return f'🔖 {sym["label"]}'
        kr_reverse = {v: k for k, v in STAMP_KR.items()}
        kr = kr_reverse.get(sname)
        if kr:
            return f'🔖 {kr}'
        return f'🔖 {format_stamp_label(sname)}'

    @staticmethod
    def _shape_current_label(tool, fallback: str) -> str:
        _SHAPE_KR = {
            'rect': '사각형', 'circle': '원', 'triangle': '삼각형',
            'pentagon': '오각형', 'hexagon': '육각형',
        }
        shape = getattr(tool, 'shape_type', '')
        kr = _SHAPE_KR.get(shape)
        return f'⬛ {kr}' if kr else fallback

