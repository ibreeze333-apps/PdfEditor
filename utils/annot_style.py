from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QColor

DASH_PRESETS: dict[str, list[float] | None] = {
    '실선': [],
    '점선': [1.2, 3.0],
    '파선': [6.0, 4.0],
    '중파선': [12.0, 6.0],
    '강조선': None,   # 두꺼운 컬러 외곽 + 흰 중심선 이중 획
    '물결무늬': None,
}

_DASH_ALIASES: dict[str, str] = {
    '장파선': '중파선',
    '물결': '물결무늬',
    # 과거 인코딩 깨짐으로 저장된 설정값 복구용 — 깨진 이름은 물음표 연속으로
    # 저장되므로 글자 수로 원래 스타일을 추정한다 (리터럴로 쓰면 mojibake
    # 검사 훅에 걸리므로 코드로 생성).
    '?' * 2: '실선',
    '?' * 3: '중파선',
    '?' * 4: '물결무늬',
}

STROKE_WIDTH_OPTIONS: list[float] = [0.5, 1.0, 1.5] + [float(v) for v in range(2, 13)]
PRESET_TOOLS: tuple[str, ...] = (
    'highlight', 'pencil', 'underline', 'strikethrough', 'line', 'arrow', 'double_arrow', 'shape'
)


class AnnotStyle:
    """Shared style state for annotation tools."""

    def __init__(self):
        self.color = QColor(255, 220, 0)
        self.opacity = 0.6
        self.width = 1.5
        self.dashes: list[float] = []
        self.dash_name = '실선'
        self.arrow_head = 'closed'
        self.arrow_fill = 'filled'

    def fitz_color(self) -> list[float]:
        return [self.color.redF(), self.color.greenF(), self.color.blueF()]

    def is_wavy(self) -> bool:
        return self.dash_name == '물결무늬'

    def is_emphasized(self) -> bool:
        return self.dash_name == '강조선'

    def set_dash(self, name: str):
        normalized = normalize_dash_name(name)
        self.dash_name = normalized
        value = DASH_PRESETS.get(normalized, [])
        self.dashes = [] if value is None else list(value)


_shared = AnnotStyle()
_tool_styles: dict[str, AnnotStyle] = {}

_TOOL_DEFAULTS: dict[str, dict] = {
    'highlight':     {'color': QColor(255, 220, 0),  'opacity': 0.4, 'width': 0.5},
    'underline':     {'color': QColor(220, 50, 50),  'opacity': 1.0, 'width': 1.5},
    'strikethrough': {'color': QColor(220, 50, 50),  'opacity': 1.0, 'width': 1.5},
    'pencil':        {'color': QColor(30, 30, 30),   'opacity': 1.0, 'width': 2.0},
    'line':          {'color': QColor(30, 30, 30),   'opacity': 1.0, 'width': 2.0},
    'arrow':         {'color': QColor(220, 50, 50),  'opacity': 1.0, 'width': 2.0},
    'double_arrow':  {'color': QColor(220, 50, 50),  'opacity': 1.0, 'width': 2.0},
    'block_arrow':   {'color': QColor(220, 50, 50),  'opacity': 1.0, 'width': 2.0},
    'shape':         {'color': QColor(50, 100, 200), 'opacity': 1.0, 'width': 2.0},
    'mosaic':        {'color': QColor(30, 30, 30),   'opacity': 1.0, 'width': 1.0},
    'text':          {'color': QColor(30, 30, 30),   'opacity': 1.0, 'width': 1.0},
}

# 공장 기본값 스냅샷 — _TOOL_DEFAULTS 는 앱 시작 시 사용자 저장값으로
# 덮어써지므로(apply_settings_defaults) '기본값으로 초기화'용 원본을 보존
_TOOL_FACTORY_DEFAULTS: dict[str, dict] = {
    name: {'color': QColor(v['color']), 'opacity': v['opacity'], 'width': v['width']}
    for name, v in _TOOL_DEFAULTS.items()
}


def scene_width(width: float, view, minimum: float = 0.5) -> float:
    """PDF 포인트 단위 선 굵기 → 캔버스 씬 단위.

    미리보기 도형은 페이지 좌표를 view.zoom() 배로 확대해 그린다. 선 굵기에도
    같은 배율을 적용해야 'PDF에 적용'한 뒤의 실제 굵기와 미리보기가 같아진다.
    (적용하면 선이 굵어져 보이던 문제의 원인)
    """
    try:
        z = float(view.zoom())
    except Exception:
        z = 1.0
    return max(minimum, float(width) * z)


def scene_dashes(dashes, width: float = 1.0) -> list[float]:
    """대시 패턴을 Qt QPen 용으로 돌려준다.

    DASH_PRESETS 값은 '선 굵기의 배수'로 해석한다 — QPen.setDashPattern 과
    같은 의미다. PDF 로 커밋할 때만 굵기를 곱해 포인트로 바꾼다
    (utils.pending_layer._int_dashes).
    """
    return [max(0.01, float(v)) for v in (dashes or [])]


def factory_tool_defaults() -> dict[str, dict]:
    """사용자 설정으로 오염되지 않은 도구 공장 기본값 사본을 반환."""
    return {
        name: {'color': QColor(v['color']),
               'opacity': v['opacity'], 'width': v['width']}
        for name, v in _TOOL_FACTORY_DEFAULTS.items()
    }

_PRESETS_PATH = Path.home() / '.pdf_editor_presets.json'

_BUILTIN_PRESETS: dict[str, list[dict]] = {
    'highlight': [
        {'name': '노랑 형광펜', 'color': '#FFDC00', 'opacity': 0.4, 'width': 4.0},
        {'name': '초록 형광펜', 'color': '#69F0AE', 'opacity': 0.35, 'width': 4.0},
        {'name': '파랑 형광펜', 'color': '#40C4FF', 'opacity': 0.35, 'width': 4.0},
        {'name': '분홍 형광펜', 'color': '#FF80AB', 'opacity': 0.4, 'width': 4.0},
    ],
    'pencil': [
        {'name': '검정 연필', 'color': '#1E1E1E', 'width': 2.0, 'dash': '실선'},
        {'name': '파란 연필', 'color': '#1565C0', 'width': 1.5, 'dash': '실선'},
        {'name': '빨간 연필', 'color': '#C62828', 'width': 2.0, 'dash': '실선'},
        {'name': '굵은 연필', 'color': '#1E1E1E', 'width': 5.0, 'dash': '실선'},
    ],
    'underline': [
        {'name': '빨간 밑줄', 'color': '#DC3232', 'width': 1.5, 'dash': '실선'},
        {'name': '점선 밑줄', 'color': '#555555', 'width': 1.5, 'dash': '점선'},
        {'name': '파선 밑줄', 'color': '#555555', 'width': 1.5, 'dash': '파선'},
        {'name': '중파선 밑줄', 'color': '#555555', 'width': 1.5, 'dash': '중파선'},
        {'name': '물결 밑줄', 'color': '#DC3232', 'width': 1.5, 'dash': '물결무늬'},
    ],
    'strikethrough': [
        {'name': '빨간 취소선', 'color': '#DC3232', 'width': 1.5, 'dash': '실선'},
        {'name': '점선 취소선', 'color': '#666666', 'width': 1.5, 'dash': '점선'},
        {'name': '파선 취소선', 'color': '#666666', 'width': 1.5, 'dash': '파선'},
        {'name': '중파선 취소선', 'color': '#666666', 'width': 1.5, 'dash': '중파선'},
    ],
    'line': [
        {'name': '보통 직선', 'color': '#1E1E1E', 'width': 1.5, 'dash': '실선'},
        {'name': '점선 직선', 'color': '#1E1E1E', 'width': 1.5, 'dash': '점선'},
        {'name': '파선 직선', 'color': '#1E1E1E', 'width': 2.0, 'dash': '파선'},
        {'name': '중파선 직선', 'color': '#1E1E1E', 'width': 2.0, 'dash': '중파선'},
        {'name': '강조 직선', 'color': '#DC3232', 'width': 4.0, 'dash': '강조선'},
    ],
    'arrow': [
        {'name': '닫힌 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '실선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
        {'name': '열린 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '실선', 'arrow_head': 'open', 'arrow_fill': 'hollow'},
        {'name': '빈 닫힌 화살표', 'color': '#DC3232', 'width': 3.0, 'dash': '실선', 'arrow_head': 'closed', 'arrow_fill': 'hollow'},
        {'name': '중파선 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '중파선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
        {'name': '강조 화살표', 'color': '#DC3232', 'width': 4.0, 'dash': '강조선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
    ],
    'double_arrow': [
        {'name': '닫힌 양방향 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '실선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
        {'name': '열린 양방향 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '실선', 'arrow_head': 'open', 'arrow_fill': 'hollow'},
        {'name': '빈 닫힌 양방향 화살표', 'color': '#DC3232', 'width': 3.0, 'dash': '실선', 'arrow_head': 'closed', 'arrow_fill': 'hollow'},
        {'name': '중파선 양방향 화살표', 'color': '#DC3232', 'width': 2.0, 'dash': '중파선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
        {'name': '강조 양방향 화살표', 'color': '#DC3232', 'width': 4.0, 'dash': '강조선', 'arrow_head': 'closed', 'arrow_fill': 'filled'},
    ],
    'shape': [
        {'name': '빈 도형', 'color': '#3264C8', 'width': 2.0, 'dash': '실선'},
        {'name': '점선 도형', 'color': '#3264C8', 'width': 2.0, 'dash': '점선'},
        {'name': '파선 도형', 'color': '#3264C8', 'width': 2.0, 'dash': '파선'},
        {'name': '중파선 도형', 'color': '#3264C8', 'width': 2.0, 'dash': '중파선'},
    ],
}

_user_presets: dict[str, list[dict]] = {}


def normalize_dash_name(name: str | None) -> str:
    if not name:
        return '실선'
    value = _DASH_ALIASES.get(str(name), str(name))
    return value if value in DASH_PRESETS else '실선'


def normalize_preset(tool_name: str, preset: dict) -> dict:
    normalized = dict(preset)
    if 'dash' in normalized:
        normalized['dash'] = normalize_dash_name(normalized.get('dash'))
    return normalized


def shared_style() -> AnnotStyle:
    return _shared


def tool_style(name: str) -> AnnotStyle:
    if name not in _tool_styles:
        style = AnnotStyle()
        defs = _TOOL_DEFAULTS.get(name, {})
        if 'color' in defs:
            style.color = defs['color']
        if 'opacity' in defs:
            style.opacity = float(defs['opacity'])
        if 'width' in defs:
            style.width = float(defs['width'])
        _tool_styles[name] = style
    return _tool_styles[name]


def _load_user_presets():
    global _user_presets
    if not _PRESETS_PATH.exists():
        _user_presets = {}
        return
    try:
        raw = json.loads(_PRESETS_PATH.read_text(encoding='utf-8'))
        _user_presets = {
            tool_name: [normalize_preset(tool_name, preset) for preset in presets]
            for tool_name, presets in raw.items()
        }
    except Exception:
        _user_presets = {}


def _save_user_presets():
    try:
        _PRESETS_PATH.write_text(
            json.dumps(_user_presets, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
    except Exception as exc:
        print(f'[annot_style] preset save error: {exc}')


def get_presets(tool_name: str) -> list[dict]:
    builtin = [normalize_preset(tool_name, preset) for preset in _BUILTIN_PRESETS.get(tool_name, [])]
    user = [normalize_preset(tool_name, preset) for preset in _user_presets.get(tool_name, [])]
    return builtin + user


def apply_preset(tool_name: str, preset: dict):
    normalized = normalize_preset(tool_name, preset)
    style = tool_style(tool_name)
    if 'color' in normalized:
        style.color = QColor(normalized['color'])
    if 'opacity' in normalized:
        style.opacity = float(normalized['opacity'])
    if 'width' in normalized:
        style.width = float(normalized['width'])
    if 'dash' in normalized:
        style.set_dash(str(normalized['dash']))
    if 'arrow_head' in normalized:
        style.arrow_head = str(normalized['arrow_head'])
    if 'arrow_fill' in normalized:
        style.arrow_fill = str(normalized['arrow_fill'])


def add_user_preset(tool_name: str, preset: dict):
    _user_presets.setdefault(tool_name, [])
    normalized = normalize_preset(tool_name, preset)
    _user_presets[tool_name] = [
        item for item in _user_presets[tool_name]
        if item.get('name') != normalized.get('name')
    ]
    _user_presets[tool_name].append(normalized)
    _save_user_presets()


def delete_user_preset(tool_name: str, preset_name: str):
    if tool_name not in _user_presets:
        return
    _user_presets[tool_name] = [
        item for item in _user_presets[tool_name]
        if item.get('name') != preset_name
    ]
    _save_user_presets()


def is_user_preset(tool_name: str, preset_name: str) -> bool:
    return any(item.get('name') == preset_name for item in _user_presets.get(tool_name, []))


def apply_settings_defaults(tool_defaults: dict):
    for name, vals in tool_defaults.items():
        _TOOL_DEFAULTS.setdefault(name, {})
        if 'color' in vals:
            _TOOL_DEFAULTS[name]['color'] = QColor(vals['color'])
        if 'opacity' in vals:
            _TOOL_DEFAULTS[name]['opacity'] = float(vals['opacity'])
        if 'width' in vals:
            _TOOL_DEFAULTS[name]['width'] = float(vals['width'])
        if name in _tool_styles:
            style = _tool_styles[name]
            if 'color' in vals:
                style.color = QColor(vals['color'])
            if 'opacity' in vals:
                style.opacity = float(vals['opacity'])
            if 'width' in vals:
                style.width = float(vals['width'])


_load_user_presets()
