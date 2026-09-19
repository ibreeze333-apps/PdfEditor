# ui/glass_button.py — 공유 GlassButton 위젯
from __future__ import annotations
from pathlib import Path
from ui.liquid_glass import paint_liquid_glass
from PySide6.QtCore import Qt, QEvent, QRectF, QSize, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QPen, QLinearGradient, QRadialGradient,
    QPainterPath, QPixmap,
)
from PySide6.QtWidgets import QApplication, QPushButton


# 유리 알약 텍스처 — 무채색 반투명 PNG 한 장을 9-슬라이스로 늘려 쓴다.
# 안쪽이 비어 있어서 밑에 깐 도구 색이 그대로 비친다.
_ASSETS_DIR  = Path(__file__).resolve().parent / 'assets'
_PILL_FILE   = _ASSETS_DIR / 'glass_pill.png'
_PILL_CANVAS = (827, 160)   # 텍스처 원본 크기
_PILL_CORNER = 80           # 9-슬라이스 모서리 조각(= 캔버스 높이의 절반, 알약)
_PILL_PAD    = 9.9          # 캔버스 가장자리 ~ 유리 본체 사이 여백(그림자용)
_PILL_RIM    = 0.09         # 유리 테 두께 / 유리 본체 높이

# 공유 버튼 렌더러. liquid는 메인 메뉴와 같은 해상도 독립 유리 표면을 쓴다.
#   'liquid' — 캡슐 유리, 다층 반사, 색 분산 (기본값)
#   'metal' — 은색 베벨 테를 두른 라운드 사각형
#   'plate' — 얇은 금속 테두리선을 두른 반투명 유리 판
#   'pill'  — 유리 알약 텍스처(glass_pill.png)
# 시안을 비교할 때 이 값만 바꾸면 된다.
BUTTON_STYLE = 'liquid'


class GlassButton(QPushButton):
    _pill: QPixmap | None = None
    _pill_loaded = False

    @classmethod
    def _pill_tex(cls) -> QPixmap | None:
        """유리 텍스처를 한 번만 읽어 캐시한다. 없으면 None(직접 그리기로 대체)."""
        if not cls._pill_loaded:
            cls._pill_loaded = True
            if _PILL_FILE.exists():
                pm = QPixmap(str(_PILL_FILE))
                cls._pill = pm if not pm.isNull() else None
        return cls._pill

    def sizeHint(self) -> QSize:
        """텍스트 폭에 맞춘 촘촘한 크기 — 툴바가 불필요하게 넓어지지 않게 한다.
        (기본 QPushButton 은 좌우 여백이 커서 버튼 여러 개가 한 줄을 넘겨
        맨 오른쪽 버튼이 잘리는 원인이 됐다.)"""
        if self._button_style == 'metal' and self._classic_style_sheet:
            return super().sizeHint().expandedTo(QSize(0, self.minimumHeight()))
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.display_text())
        # 좌우 여백은 글자 크기에 비례시킨다 — 툴바가 글꼴을 줄여 폭을
        # 맞출 때 여백도 같이 줄어야 실제로 좁아진다.
        # (13pt 기준 20px 로, 예전 고정값과 같은 여백이 나온다)
        liquid = self._button_style == 'liquid'
        pad = max(28, round(fm.height() * 1.35)) if liquid else max(9, round(fm.height() * .75))
        if self.is_compact():
            # 아이콘 하나만 남으면 좌우 여백도 줄인다 — 여백이 그대로면 줄어든 폭이 거의 없다
            pad = max(16, round(fm.height() * 0.8))
        # 최소폭(디자인 기준값)도 글꼴 배율만큼 같이 줄인다 — 툴바가 글꼴을
        # 줄여 폭을 맞출 때 최소폭이 그대로면 거기서 더 못 줄어든다.
        w = max(self._scaled_min_width(), text_w + pad)
        h = max(self.minimumHeight(), fm.height() + (23 if liquid else 12))
        return QSize(w, h)

    def setMinimumWidth(self, w: int):
        """호출자가 준 값은 '디자인 기준 최소폭'으로 기억해 둔다.

        툴바가 글꼴을 줄여 폭을 맞출 때 이 값도 같이 낮춰야 한다.
        (하드 최소폭이 그대로면 레이아웃이 그 아래로 못 내려가서,
        글자만 작아지고 버튼 폭은 그대로인 상태가 된다.)
        """
        self._design_min_w = int(w)
        super().setMinimumWidth(self._scaled_min_width())

    def _scaled_min_width(self) -> int:
        """앱 기본 글꼴 대비 현재 글꼴 비율만큼 줄인 최소폭."""
        if self.is_compact():
            return 0
        floor = getattr(self, '_design_min_w', 0)
        if floor <= 0:
            return 0
        app = QApplication.font().pointSizeF()
        cur = self.font().pointSizeF()
        if app > 0 and 0 < cur < app:
            return max(24, int(floor * cur / app))
        return floor

    def changeEvent(self, event):
        # 글꼴이 바뀌면 최소폭 기준도 다시 잡는다
        if event.type() == QEvent.Type.FontChange:
            super().setMinimumWidth(self._scaled_min_width())
            self.updateGeometry()
        super().changeEvent(event)

    def minimumSizeHint(self) -> QSize:
        """최소 크기도 글자 폭에 맞춘다.

        기본값(QPushButton)은 이보다 작아서, 툴바가 좁아지면 Qt 가 버튼을
        글자보다 좁게 눌러 버렸다. 그러면 가운데 정렬한 글씨가 잘려
        '조금씩 틀어져' 보인다. 여기서 막고, 모자란 폭은 툴바 쪽에서
        줄바꿈으로 해결한다(ui/flow_bar.py).
        """
        return self.sizeHint()

    # ── 컴팩트(아이콘만) 표시 ─────────────────────────────────────────
    #
    # 화면이 좁아 툴바가 여러 줄로 넘칠 때 FlowBar 가 켠다. '🖌 형광펜' 처럼
    # 앞에 아이콘이 붙은 버튼은 아이콘만 보이고 이름은 툴팁으로 옮긴다.
    # 아이콘이 없는 버튼('PDF 저장' 등)은 글자를 그대로 둔다.
    # text() 는 바꾸지 않는다 — 버튼 이름을 읽는 다른 코드가 그대로 동작하게.

    def compact_label(self) -> str:
        """컴팩트일 때 보일 아이콘. 없으면 빈 문자열."""
        text = (self.text() or '').strip()
        head, sep, rest = text.partition(' ')
        if not sep or not rest.strip() or len(head) > 3:
            return ''
        # 글자(한글·영문·숫자)가 섞여 있으면 아이콘이 아니다
        if any(ch.isalnum() for ch in head):
            return ''
        return head

    def can_compact(self) -> bool:
        if self._button_style == 'metal' and self._classic_style_sheet:
            return False           # 기존 스타일은 Qt 가 글자를 직접 그린다
        return bool(self.compact_label())

    def is_compact(self) -> bool:
        return self._compact and self.can_compact()

    def display_text(self) -> str:
        return self.compact_label() if self.is_compact() else self.text()

    def set_compact(self, on: bool):
        on = bool(on)
        if on == self._compact:
            return
        self._compact = on
        if on and self.can_compact() and not self.toolTip():
            self.setToolTip(self.text())
            self._auto_tip = True
        elif not on and self._auto_tip:
            self.setToolTip('')
            self._auto_tip = False
        super().setMinimumWidth(self._scaled_min_width())
        self.updateGeometry()
        self.update()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._button_style = BUTTON_STYLE
        self._classic_style_sheet = ''
        self._hover = False
        self._design_min_w = 0
        self._compact = False      # 툴바가 좁을 때 아이콘만 보이는 상태
        self._auto_tip = False     # 컴팩트 때문에 자동으로 넣은 툴팁인지
        self._visual_variant = 'default'
        self._accent: QColor | None = None   # 버튼별 유리 색조
        self._frost_pixmap: QPixmap | None = None
        self._frost_src = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)
        # 클릭해도 캔버스 포커스를 빼앗지 않는다 — 버튼을 누른 뒤
        # 방향키 페이지 넘김이 계속 동작해야 한다
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet('QPushButton { border: none; background: transparent; font-weight: 600; }')

    def set_button_style(self, style):
        self._button_style = 'metal' if style == 'classic' else 'liquid'
        self.setMinimumHeight(38 if style == 'classic' else 48)
        if style == 'classic' and self._classic_style_sheet:
            self.setStyleSheet(self._classic_style_sheet)
        else:
            weight = 500 if style == 'classic' else 600
            self.setStyleSheet(f'QPushButton {{ border: none; background: transparent; font-weight: {weight}; }}')
        self.updateGeometry()
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def set_frost_cache(self, pixmap: QPixmap | None, src_rect=None):
        self._frost_pixmap = pixmap
        self._frost_src = src_rect
        self.update()

    def set_visual_variant(self, variant: str):
        self._visual_variant = variant or 'default'
        self.update()

    def set_accent(self, color):
        """이 버튼의 유리 색조를 정한다. 지정하면 반투명 유리(글래스모피즘)
        스타일로, 지정하지 않으면 기존 파란 캡슐로 그린다."""
        self._accent = QColor(color) if color else None
        self.update()

    @staticmethod
    def _mix(c: QColor, other: QColor, t: float) -> QColor:
        """c 와 other 를 t(0~1) 비율로 섞는다."""
        t = max(0.0, min(1.0, t))
        return QColor(round(c.red() * (1 - t) + other.red() * t),
                      round(c.green() * (1 - t) + other.green() * t),
                      round(c.blue() * (1 - t) + other.blue() * t))

    @staticmethod
    def _draw_nine(p: QPainter, pix: QPixmap, w: float, h: float):
        """9-슬라이스로 늘린다 — 모서리는 비율대로만 줄이고 가운데만 늘린다.

        그냥 늘리면 알약 끝의 곡률과 유리 테 두께가 버튼 너비에 따라 찌그러진다.
        """
        CW, CH = _PILL_CANVAS
        sc = min(_PILL_CORNER, CW // 2, CH // 2)
        c = max(2.0, sc * h / CH)
        c = min(c, w / 2.0 - 0.5, h / 2.0)      # 좁은 버튼에서 조각이 겹치지 않게
        xs_s = (0.0, float(sc), float(CW - sc), float(CW))
        ys_s = (0.0, float(sc), float(CH - sc), float(CH))
        xs_d = (0.0, c, w - c, w)
        ys_d = (0.0, c, h - c, h)
        for i in range(3):
            for j in range(3):
                dw, dh = xs_d[i + 1] - xs_d[i], ys_d[j + 1] - ys_d[j]
                if dw <= 0 or dh <= 0:
                    continue
                p.drawPixmap(
                    QRectF(xs_d[i], ys_d[j], dw, dh), pix,
                    QRectF(xs_s[i], ys_s[j],
                           xs_s[i + 1] - xs_s[i], ys_s[j + 1] - ys_s[j]))

    def _paint_pill(self, p: QPainter, state: str, text_raw: str, pix: QPixmap):
        """도구 색을 깔고 그 위에 유리 텍스처를 얹는다."""
        white = QColor(255, 255, 255)
        acc = self._accent or QColor(120, 170, 240)
        w, h = float(self.width()), float(self.height())
        CH = _PILL_CANVAS[1]
        k = h / CH
        pad = _PILL_PAD * k
        glass_h = max(1.0, h - 2 * pad)
        rim = glass_h * _PILL_RIM

        checked = (state == 'checked')
        pressed = (state == 'pressed')
        hover = (state == 'hover')

        # ── 색 밑판 — 유리 테 밑으로 살짝 들어가게 넣어 가장자리에 색이 새지 않게 ──
        ins = pad + rim * 0.35
        fill = QRectF(ins, ins, max(1.0, w - 2 * ins), max(1.0, h - 2 * ins))
        r = fill.height() / 2.0
        body = QPainterPath()
        body.addRoundedRect(fill, r, r)

        if checked:
            top, bot = self._mix(acc, white, 0.16), self._mix(acc, QColor(0, 0, 0), 0.16)
            text_color = white
        else:
            base = 0.60 if not hover else 0.50
            top = self._mix(acc, white, base + 0.16)
            bot = self._mix(acc, white, base - 0.16)
            if pressed:
                top, bot = self._mix(acc, white, base - 0.06), self._mix(acc, white, base - 0.26)
            text_color = QColor(28, 32, 40)

        grad = QLinearGradient(fill.topLeft(), fill.bottomLeft())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.fillPath(body, grad)

        # ── 유리 텍스처 ──
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw_nine(p, pix, w, h)

        # ── 눌림/활성 표시 — 텍스처는 한 장이므로 명암으로 상태를 구분한다 ──
        if pressed:
            p.fillPath(body, QColor(30, 44, 74, 26))
        elif checked:
            p.fillPath(body, QColor(30, 44, 74, 14))

        if checked:
            f = p.font(); f.setBold(True); p.setFont(f)
        p.setPen(text_color)
        p.drawText(QRectF(pad, pad, max(1.0, w - 2 * pad), max(1.0, h - 2 * pad)),
                   Qt.AlignmentFlag.AlignCenter, text_raw)

    def _paint_plate(self, p: QPainter, state: str, text_raw: str):
        """얇은 금속 테두리선을 두른 반투명 유리 판.

        원본 이미지(3d-set-of-rectangle-glass-plates)에서 비율과 색을 재서
        그린다. 이미지를 그대로 늘려 쓰면 원본에 겹쳐 있는 '어긋난 흰 판'과
        아래쪽 빛무리가 버튼 크기에서 얼룩으로 보여서 직접 그린다.
        """
        white = QColor(255, 255, 255)
        acc = self._accent or QColor(120, 170, 240)
        w, h = float(self.width()), float(self.height())

        checked = (state == 'checked')
        pressed = (state == 'pressed')
        hover = (state == 'hover')

        # 원본 비율: 위 여백 5%, 아래 그림자 19%, 좌우 7.5%, 모서리 9%
        body = QRectF(w * 0.020, h * 0.055,
                      max(2.0, w * 0.960), max(2.0, h * 0.755))
        if pressed:
            body.translate(0.0, 0.8)
        r = max(2.5, body.height() * 0.12)

        # ── 아래 그림자 ──
        for i, alpha in enumerate((10, 14, 20) if not pressed else (8, 11, 0)):
            if not alpha:
                continue
            sp = QPainterPath()
            sp.addRoundedRect(body.adjusted(-i * 0.5, 2.0 - i * 0.2,
                                            i * 0.9, 2.2 + i * 0.8), r, r)
            p.fillPath(sp, QColor(30, 44, 60, alpha))

        face = QPainterPath()
        face.addRoundedRect(body, r, r)

        # ── 색 면 ──
        if checked:
            top, bot = self._mix(acc, white, 0.10), self._mix(acc, QColor(0, 0, 0), 0.22)
            text_color = white
        else:
            base = 0.46 if not hover else 0.34
            top = self._mix(acc, white, base + 0.20)
            bot = self._mix(acc, white, base - 0.10)
            if pressed:
                top, bot = self._mix(acc, white, base - 0.06), self._mix(acc, white, base - 0.24)
            text_color = QColor(26, 30, 38)

        fg = QLinearGradient(body.topLeft(), body.bottomLeft())
        fg.setColorAt(0.0, top)
        fg.setColorAt(1.0, bot)
        p.fillPath(face, fg)

        p.save()
        p.setClipPath(face)

        # ── 유리 특유의 사선 반사 — 왼쪽 위에서 오른쪽 아래로 지나가는 띠 ──
        sheen = QLinearGradient(body.topLeft(), body.bottomRight())
        sheen.setColorAt(0.00, QColor(255, 255, 255, 96))
        sheen.setColorAt(0.34, QColor(255, 255, 255, 60))
        sheen.setColorAt(0.36, QColor(255, 255, 255, 16))
        sheen.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.fillRect(body, sheen)

        # ── 아래 가장자리 빛무리 — 원본 판 아래 가운데의 밝은 반사 ──
        if not checked:
            cx = body.center().x()
            rad = QRadialGradient(QPointF(cx, body.bottom()), body.width() * 0.42)
            rad.setColorAt(0.0, QColor(255, 255, 255, 130 if not pressed else 60))
            rad.setColorAt(0.45, QColor(255, 255, 255, 46 if not pressed else 20))
            rad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(body, rad)
        p.restore()

        # ── 얇은 금속 테두리선 — 위/왼쪽은 밝고 아래/오른쪽은 어둡다 ──
        edge = QLinearGradient(body.topLeft(), body.bottomRight())
        edge.setColorAt(0.00, QColor(255, 255, 255, 240))
        edge.setColorAt(0.30, QColor(198, 205, 210, 215))
        edge.setColorAt(0.62, QColor(146, 156, 164, 210))
        edge.setColorAt(1.00, QColor(116, 128, 138, 220))
        p.setPen(QPen(edge, 1.0))
        p.drawPath(face)
        # 안쪽으로 한 줄 더 — 판에 두께가 있는 것처럼 보이게
        inner = QPainterPath()
        inner.addRoundedRect(body.adjusted(1.0, 1.0, -1.0, -1.0),
                             max(1.5, r - 1.0), max(1.5, r - 1.0))
        p.setPen(QPen(QColor(255, 255, 255, 96), 1.0))
        p.drawPath(inner)

        if checked:
            f = p.font(); f.setBold(True); p.setFont(f)
        p.setPen(text_color)
        p.drawText(body, Qt.AlignmentFlag.AlignCenter, text_raw)

    def _paint_metal(self, p: QPainter, state: str, text_raw: str):
        """금속 베벨 테를 두른 라운드 사각형 버튼.

        바깥에서 안으로: 흐린 바닥 그림자 → 크롬 테(위·아래에 흰 반사가
        들어간 세로 그라디언트) → 도구 색 면. 테는 항상 은색이라 색이
        달라도 버튼들이 한 벌로 보인다.
        """
        white = QColor(255, 255, 255)
        acc = self._accent or QColor(120, 170, 240)
        w, h = float(self.width()), float(self.height())

        checked = (state == 'checked')
        pressed = (state == 'pressed')
        hover = (state == 'hover')

        outer = QRectF(1.4, 0.8, max(2.0, w - 2.8), max(2.0, h - 3.6))
        if pressed:
            outer.translate(0.0, 1.0)
        r = max(4.0, outer.height() * 0.18)
        rim = max(2.4, outer.height() * 0.115)

        # ── 바닥 그림자 — 같은 모양을 알파를 낮춰 겹쳐 흐림을 흉내낸다 ──
        for i, alpha in enumerate((14, 18, 24) if not pressed else (10, 13, 0)):
            if not alpha:
                continue
            sp = QPainterPath()
            sp.addRoundedRect(outer.adjusted(-i * 0.7, 2.2 - i * 0.2,
                                             i * 0.7, 2.4 + i * 0.7), r, r)
            p.fillPath(sp, QColor(36, 44, 62, alpha))

        # ── 크롬 테 ──
        body = QPainterPath()
        body.addRoundedRect(outer, r, r)
        rg = QLinearGradient(outer.topLeft(), outer.bottomLeft())
        rg.setColorAt(0.00, QColor(176, 181, 189))
        rg.setColorAt(0.07, QColor(255, 255, 255))
        rg.setColorAt(0.26, QColor(219, 223, 229))
        rg.setColorAt(0.52, QColor(150, 156, 165))
        rg.setColorAt(0.78, QColor(203, 208, 215))
        rg.setColorAt(0.94, QColor(255, 255, 255))
        rg.setColorAt(1.00, QColor(171, 176, 184))
        p.fillPath(body, rg)
        # 가로 방향 사선 반사 — 금속 느낌을 더한다
        sheen = QLinearGradient(outer.topLeft(), outer.topRight())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.22, QColor(255, 255, 255, 74))
        sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.8, QColor(255, 255, 255, 58))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(body, sheen)

        # ── 색 면 ──
        inner = outer.adjusted(rim, rim, -rim, -rim)
        ir = max(2.0, r - rim * 0.8)
        face = QPainterPath()
        face.addRoundedRect(inner, ir, ir)

        if checked:
            top, bot = self._mix(acc, white, 0.10), self._mix(acc, QColor(0, 0, 0), 0.22)
            text_color = white
        else:
            base = 0.50 if not hover else 0.38
            top = self._mix(acc, white, base + 0.18)
            bot = self._mix(acc, white, base - 0.14)
            if pressed:
                top, bot = self._mix(acc, white, base - 0.06), self._mix(acc, white, base - 0.24)
            text_color = QColor(28, 32, 40)

        fg = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fg.setColorAt(0.0, top)
        fg.setColorAt(1.0, bot)
        p.fillPath(face, fg)

        # 면이 테보다 한 단 들어가 보이도록 위쪽 안쪽 그림자
        p.save()
        p.setClipPath(face)
        sh = QLinearGradient(inner.topLeft(),
                             QPointF(inner.left(), inner.top() + rim * 1.5))
        sh.setColorAt(0.0, QColor(48, 56, 72, 74 if not pressed else 104))
        sh.setColorAt(1.0, QColor(48, 56, 72, 0))
        p.fillRect(inner, sh)
        p.restore()

        # ── 윤곽선 — 바깥은 어둡게, 면 경계는 밝게 ──
        p.setPen(QPen(QColor(112, 118, 128, 150), 1.0))
        p.drawPath(body)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
        p.drawPath(face)

        if checked:
            f = p.font(); f.setBold(True); p.setFont(f)
        p.setPen(text_color)
        p.drawText(inner, Qt.AlignmentFlag.AlignCenter, text_raw)

    def _paint_glass(self, p: QPainter, state: str, text_raw: str):
        """두꺼운 유리 조각처럼 그린다.

        바깥에 밝은 유리 림(테두리 두께)을 두고, 그 안에 반투명 색면을 넣은
        이중 구조다. 위쪽에 강한 반사 광택, 아래쪽에 은은한 무지개빛을 얹어
        실제 유리 버튼처럼 보이게 한다.
        """
        white = QColor(255, 255, 255)
        acc = self._accent or QColor(120, 170, 240)
        rect = QRectF(self.rect())
        outer = rect.adjusted(1.6, 1.6, -1.6, -2.6)
        # 유리 테두리 두께·모서리는 버튼 크기에 비례시킨다 — 작은 툴바 버튼과
        # 큰 버튼 모두에서 같은 '유리 조각' 비율로 보이게.
        rim = max(3.0, min(9.0, outer.height() * 0.11))
        r = max(9.0, min(20.0, outer.height() * 0.30))

        pressed = (state == 'pressed')
        checked = (state == 'checked')
        hover = (state == 'hover')

        # ── 바닥 그림자 (유리가 떠 있는 느낌) ──
        sh = QPainterPath()
        sh.addRoundedRect(outer.adjusted(1.2, 2.6, 1.4, 3.4), r, r)
        p.fillPath(sh, QColor(40, 52, 84, 20 if pressed else 32))

        # ── 바깥 유리 림 ──
        body = QPainterPath()
        body.addRoundedRect(outer, r, r)
        # 림은 거의 흰빛이라 두께 자체가 '빛나는 유리 테'로 읽힌다.
        rim_grad = QLinearGradient(outer.topLeft(), outer.bottomLeft())
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        rim_grad.setColorAt(0.30, self._mix(acc, white, 0.93))
        rim_grad.setColorAt(0.70, self._mix(acc, white, 0.88))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 255))
        p.fillPath(body, rim_grad)

        # ── 안쪽 색면 ──
        inner = outer.adjusted(rim, rim, -rim, -rim)
        ir = max(4.0, r - rim + 0.5)
        face = QPainterPath()
        face.addRoundedRect(inner, ir, ir)

        if checked:
            top = self._mix(acc, white, 0.20)
            bot = self._mix(acc, QColor(0, 0, 0), 0.20)
            text_color = white
        else:
            base = 0.78 if not hover else 0.68
            top = self._mix(acc, white, base + 0.14)
            bot = self._mix(acc, white, base - 0.14)
            if pressed:
                top, bot = self._mix(acc, white, base - 0.06), self._mix(acc, white, base - 0.22)
            text_color = QColor(32, 36, 44)

        fg = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fg.setColorAt(0.0, top)
        fg.setColorAt(0.55, self._mix(top, bot, 0.6))
        fg.setColorAt(1.0, bot)
        p.fillPath(face, fg)

        # 색면이 림보다 한 단 들어가 보이도록 위쪽 안쪽 그림자를 깐다.
        p.save()
        p.setClipPath(face)
        sh_in = QLinearGradient(inner.topLeft(), QPointF(inner.left(),
                                                        inner.top() + rim * 1.6))
        sh_in.setColorAt(0.0, QColor(70, 88, 130, 46))
        sh_in.setColorAt(1.0, QColor(70, 88, 130, 0))
        p.fillRect(inner, sh_in)
        p.restore()

        # ── 아래쪽 무지개 반사 ──
        if not checked:
            h, sat, v, _ = acc.getHsv()
            warm = QColor.fromHsv((h + 34) % 360, max(46, sat), 255)
            cool = QColor.fromHsv((h - 40) % 360, max(46, sat), 255)
            band = QRectF(inner.left(), inner.top() + inner.height() * 0.55,
                          inner.width(), inner.height() * 0.45)
            bp = QPainterPath()
            bp.addRoundedRect(band, ir * 0.7, ir * 0.7)
            bg = QLinearGradient(band.topLeft(), band.topRight())
            bg.setColorAt(0.0, QColor(cool.red(), cool.green(), cool.blue(), 0))
            bg.setColorAt(0.28, QColor(cool.red(), cool.green(), cool.blue(), 62))
            bg.setColorAt(0.62, QColor(warm.red(), warm.green(), warm.blue(), 58))
            bg.setColorAt(1.0, QColor(warm.red(), warm.green(), warm.blue(), 0))
            p.save(); p.setClipPath(face); p.fillPath(bp, bg); p.restore()

        # ── 상단 반사 광택 ──
        gl = QRectF(inner.left() + 1.4, inner.top() + 1.0,
                    inner.width() - 2.8, inner.height() * 0.52)
        gp = QPainterPath()
        gp.addRoundedRect(gl, ir - 1.5, ir - 1.5)
        ga = 96 if checked else (140 if pressed else 232)
        gg = QLinearGradient(gl.topLeft(), gl.bottomLeft())
        gg.setColorAt(0.0, QColor(255, 255, 255, ga))
        gg.setColorAt(0.62, QColor(255, 255, 255, int(ga * 0.30)))
        gg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(gp, gg)

        # ── 유리 테두리 선(바깥 밝게 / 안쪽 그림자) ──
        p.setPen(QPen(QColor(255, 255, 255, 235), 1.3))
        p.drawPath(body)
        p.setPen(QPen(self._mix(acc, white, 0.30 if not checked else 0.0), 1.0))
        p.drawPath(face)

        if checked:
            f = p.font(); f.setBold(True); p.setFont(f)
        p.setPen(text_color)
        p.drawText(inner, Qt.AlignmentFlag.AlignCenter, text_raw)

    def paintEvent(self, event):
        if self._button_style == 'metal' and self._classic_style_sheet:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # checked(토글 활성)와 pressed(순간 누름)를 구분한다 —
        # 활성 상태는 반전 스타일로 그려 어떤 버튼이 켜져 있는지
        # 한눈에 보이게 한다 (어두운 파랑만으로는 구분이 안 됨).
        state = 'normal'
        if self.isCheckable() and self.isChecked():
            state = 'checked'
        elif self.isDown():
            state = 'pressed'
        elif self._hover:
            state = 'hover'

        text_raw = self.display_text()

        if self._button_style == 'liquid' and self._visual_variant != 'lite_flat':
            if self.isDown():
                state = 'pressed'
            if not self.isEnabled():
                state = 'normal'
            text_rect, colour = paint_liquid_glass(
                p, QRectF(self.rect()), self._accent, state, self.isEnabled())
            p.setPen(colour)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text_raw)
            return

        # 색조가 지정된 버튼(툴바 도구 버튼)은 BUTTON_STYLE 대로 그린다
        if self._accent is not None and self._visual_variant != 'lite_flat':
            pix = None
            if self._button_style == 'pill':
                pix = self._pill_tex()
                if pix is not None:
                    self._paint_pill(p, state, text_raw, pix)
            elif self._button_style == 'plate':
                self._paint_plate(p, state, text_raw)
                return
            else:
                self._paint_metal(p, state, text_raw)
                return
            if pix is None:
                self._paint_glass(p, state, text_raw)   # 에셋이 없으면 직접 그리기
            return

        if self._visual_variant == 'lite_flat':
            outer = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
            radius = 10.5
            path = QPainterPath()
            path.addRoundedRect(outer, radius, radius)

            shadow_rect = outer.adjusted(0.0, 1.8, 0.0, 2.6)
            shadow = QPainterPath()
            shadow.addRoundedRect(shadow_rect, radius, radius)
            p.fillPath(shadow, QColor(32, 46, 80, 38 if state != 'pressed' else 24))

            p.fillPath(path, QColor(255, 255, 255, 246))
            p.setPen(QPen(QColor(228, 234, 246, 230), 1.0))
            p.drawPath(path)

            inner = outer.adjusted(4.0, 4.0, -4.0, -4.0)
            if state == 'pressed':
                inner.translate(0.0, 1.0)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(inner, radius - 3.6, radius - 3.6)

            fill_top = QColor(132, 196, 255)
            fill_mid = QColor(86, 155, 248)
            fill_bottom = QColor(46, 110, 232)
            border = QColor(206, 231, 255)
            text_color = QColor(255, 255, 255)
            bold_text = False
            if state == 'checked':
                # 활성(토글 on): 반전 — 밝은 배경 + 파란 굵은 글자 + 진한 테두리
                fill_top = QColor(255, 255, 255)
                fill_mid = QColor(240, 246, 255)
                fill_bottom = QColor(219, 232, 254)
                border = QColor(37, 99, 235)
                text_color = QColor(29, 78, 216)
                bold_text = True
            elif state == 'pressed':
                fill_top = QColor(84, 134, 219)
                fill_mid = QColor(52, 103, 199)
                fill_bottom = QColor(30, 68, 158)
                border = QColor(183, 216, 255)
                text_color = QColor(255, 255, 255)
            elif state == 'hover':
                fill_top = QColor(150, 209, 255)
                fill_mid = QColor(100, 167, 252)
                fill_bottom = QColor(58, 122, 240)
                border = QColor(221, 238, 255)
                text_color = QColor(255, 255, 255)

            grad = QLinearGradient(inner.topLeft(), inner.bottomLeft())
            grad.setColorAt(0.0, fill_top)
            grad.setColorAt(0.52, fill_mid)
            grad.setColorAt(1.0, fill_bottom)
            p.fillPath(inner_path, grad)

            gloss = QRectF(inner.left() + 1.2, inner.top() + 1.0,
                           inner.width() - 2.4, inner.height() * 0.46)
            gloss_path = QPainterPath()
            gloss_path.addRoundedRect(gloss, radius - 5.0, radius - 5.0)
            gloss_alpha = 180
            if state == 'pressed':
                gloss_alpha = 72
            elif state == 'checked':
                gloss_alpha = 30
            gloss_grad = QLinearGradient(gloss.topLeft(), gloss.bottomLeft())
            gloss_grad.setColorAt(0.0, QColor(255, 255, 255, gloss_alpha))
            gloss_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillPath(gloss_path, gloss_grad)

            band = QRectF(inner.left() + 4.0, inner.top() + inner.height() * 0.33,
                          inner.width() - 8.0, inner.height() * 0.15)
            band_path = QPainterPath()
            band_path.addRoundedRect(band, radius - 7.8, radius - 7.8)
            band_grad = QLinearGradient(band.topLeft(), band.bottomLeft())
            band_grad.setColorAt(0.0, QColor(255, 255, 255, 46 if state != 'pressed' else 18))
            band_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillPath(band_path, band_grad)

            p.setPen(QPen(border, 2.0 if state == 'checked' else 1.0))
            p.drawPath(inner_path)
            if bold_text:
                f = p.font()
                f.setBold(True)
                p.setFont(f)
            p.setPen(text_color)
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, text_raw)
            return

        # 외곽 흰 shell
        outer = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        r = 11.0
        op = QPainterPath()
        op.addRoundedRect(outer, r, r)

        p.save()
        p.translate(0, 2.0)
        shp = QPainterPath()
        shp.addRoundedRect(outer.adjusted(0.8, 0.8, 1.4, 1.8), r, r)
        p.fillPath(shp, QColor(34, 48, 78, 50 if state != 'pressed' else 34))
        p.restore()

        p.fillPath(op, QColor(255, 255, 255, 248))
        p.setPen(QPen(QColor(232, 236, 246, 230), 1.0))
        p.drawPath(op)

        # 내부 파란 그라디언트 캡슐
        inner = outer.adjusted(4.2, 4.2, -4.2, -4.2)
        ip = QPainterPath()
        ip.addRoundedRect(inner, r - 3.8, r - 3.8)

        text_color = QColor(255, 255, 255)
        border_pen = QPen(QColor(205, 228, 255, 170), 0.9)
        gloss_alpha = 178
        bold_text = False

        if state == 'checked':
            # 활성(토글 on): 반전 — 밝은 배경 + 파란 굵은 글자 + 진한 테두리
            b0, b1 = QColor(255, 255, 255), QColor(219, 232, 254)
            text_color = QColor(29, 78, 216)
            border_pen = QPen(QColor(37, 99, 235), 2.0)
            gloss_alpha = 30
            bold_text = True
        else:
            b0, b1 = QColor(116, 188, 255), QColor(52, 122, 240)
            if state == 'pressed':
                b0, b1 = b0.darker(135), b1.darker(140)
                gloss_alpha = 60
            elif state == 'hover':
                b0, b1 = b0.lighter(108), b1.lighter(108)

        ig = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        ig.setColorAt(0.0, b0)
        ig.setColorAt(1.0, b1)
        p.fillPath(ip, ig)

        # 상단 글로스
        gloss = QRectF(inner.left() + 1.4, inner.top() + 1.2,
                       inner.width() - 2.8, inner.height() * 0.46)
        gg = QLinearGradient(gloss.topLeft(), gloss.bottomLeft())
        gg.setColorAt(0.0, QColor(255, 255, 255, gloss_alpha))
        gg.setColorAt(1.0, QColor(255, 255, 255, 0))
        gp = QPainterPath()
        gp.addRoundedRect(gloss, r - 5.2, r - 5.2)
        p.fillPath(gp, gg)

        p.setPen(border_pen)
        p.drawPath(ip)

        if bold_text:
            f = p.font()
            f.setBold(True)
            p.setFont(f)
        p.setPen(text_color)
        p.drawText(inner, Qt.AlignmentFlag.AlignCenter, text_raw)
