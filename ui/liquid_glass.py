"""Resolution-independent glass surfaces shared by menus and toolbar buttons.

The light reference is reproduced as layered optical rims, a recessed colour
volume, broad softbox reflection and small chromatic caustics. No scaled bitmap
or background capture is needed, so the outline stays sharp at every DPI.
"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QMenuBar, QStyleOptionMenuItem, QStyle, QToolButton


def _mix(a, b, amount):
    a, b = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * amount) for x, y in
                    zip(a.getRgb()[:3], b.getRgb()[:3])))


def _capsule(rect):
    path = QPainterPath()
    radius = min(rect.height(), rect.width()) / 2
    path.addRoundedRect(rect, radius, radius)
    return path


def _gradient(rect, stops):
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for position, colour in stops:
        grad.setColorAt(position, QColor(colour))
    return grad


def paint_liquid_glass(p, rect, accent=None, state='normal', enabled=True):
    """Paint only the surface; return the safe text rectangle and text colour."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    scale = min(1.6, max(.65, rect.height() / 48))
    down = state == 'pressed'
    active = state == 'checked'
    hover = state == 'hover'
    acc = QColor(accent or '#9eafc1')
    if not enabled:
        acc = QColor('#bdc5ce')
        p.setOpacity(.48)
    body = QRectF(rect).adjusted(3 * scale, 3 * scale, -4 * scale, -9 * scale)
    if down:
        body.translate(0, 1.6 * scale)
    # Soft contact shadow, contained in the widget rather than cut by its edge.
    for spread in range(7, 0, -1):
        shadow = body.adjusted(-spread * .24 * scale, 0,
                               spread * .32 * scale, spread * .48 * scale)
        shadow.translate(1.2 * scale, (2 if down else 4) * scale)
        p.fillPath(_capsule(shadow), QColor(40, 53, 78, 3 + (7 - spread)))

    # The lower extrusion has its own rim, visibly below the top glass face.
    foot = body.translated(0, 3.2 * scale)
    p.fillPath(_capsule(foot), _gradient(foot, [
        (0, '#e8eff5'), (.60, '#a8b8c9'), (.79, '#eef7fc'),
        (.89, '#faffff'), (1, '#a9b8c9')]))
    p.fillPath(_capsule(body), _gradient(body, [
        (0, '#7f93a7'), (.055, '#f8fcff'), (.14, '#e6eef8'),
        (.34, '#b1c0ce'), (.55, '#869baa'), (.74, '#d1e1e9'),
        (.89, '#ffffff'), (1, '#92a7b8')]))

    # Transparent coloured volume: almost clear at rest, saturated when selected.
    inner = body.adjusted(2.7 * scale, 2.4 * scale, -2.7 * scale, -2.6 * scale)
    white = '#f4f6f9'
    if active:
        colours = [(0, _mix(acc, '#ffffff', .28)), (.35, _mix(acc, '#ffffff', .08)),
                   (.65, _mix(acc, '#13355c', .47)), (1, _mix(acc, '#7deaff', .25))]
    else:
        strength = .68 if hover else .84
        colours = [(0, _mix(acc, '#c5d0dc', .65)),
                   (.27, _mix(acc, white, strength)),
                   (.60, _mix(acc, '#e9eef3', strength)),
                   (.85, _mix(acc, '#ffffff', .64)),
                   (1, _mix(acc, '#9ce8ef', .40))]
    p.fillPath(_capsule(inner), _gradient(inner, colours))

    p.save()
    p.setClipPath(_capsule(body))
    # Localised dispersion at curved ends, rather than a rainbow across the text.
    for x, y, colour, radius in [
        (.025, .72, '#69dbed', .25), (.11, .95, '#a9b8ff', .26),
        (.85, .93, '#fff2a1', .23), (.98, .78, '#83e5f6', .24),
        (.96, .13, '#aba0e7', .18)]:
        c = QColor(colour); c.setAlpha(155 if enabled else 65)
        centre = QPointF(body.left() + body.width() * x, body.top() + body.height() * y)
        glow = QRadialGradient(centre, body.height() * radius)
        glow.setColorAt(0, c); c.setAlpha(0); glow.setColorAt(1, c)
        p.fillRect(body, glow)

    # Broad softbox reflection follows the rounded shoulder of the glass.
    gloss = inner.adjusted(2 * scale, .8 * scale, -3 * scale, 0)
    gloss.setHeight(inner.height() * .43)
    p.fillPath(_capsule(gloss), _gradient(gloss, [
        (0, QColor(255, 255, 255, 210 if not down else 115)),
        (.55, QColor(255, 255, 255, 115 if not active else 80)),
        (1, QColor(255, 255, 255, 8))]))
    # Slanted highlight on the left bevel.
    highlight = QPainterPath()
    x, y, h = body.left(), body.top(), body.height()
    highlight.moveTo(x + h * .13, y + h * .40)
    highlight.cubicTo(x + h * .08, y + h * .15, x + h * .40, y + h * .025, x + h * .64, y + h * .07)
    highlight.cubicTo(x + h * .42, y + h * .15, x + h * .30, y + h * .25, x + h * .22, y + h * .40)
    highlight.closeSubpath()
    p.fillPath(highlight, QColor(255, 255, 255, 218))
    p.restore()

    # Thin double reflection lines distinguish glass from a heavy chrome bevel.
    p.setPen(QPen(_gradient(body, [(0, '#fbfdff'), (.45, '#9aaeba'),
                                  (.76, '#ffffff'), (1, '#efffff')]), .9 * scale))
    p.drawPath(_capsule(body.adjusted(.8 * scale, .8 * scale, -.8 * scale, -.8 * scale)))
    p.setPen(QPen(QColor(255, 255, 255, 180), .8 * scale))
    p.drawPath(_capsule(inner.adjusted(.7 * scale, .5 * scale, -.7 * scale, -.5 * scale)))
    if active:
        p.setPen(QPen(_mix(acc, '#23557c', .4), 1.2 * scale))
        p.drawPath(_capsule(body))
    p.restore()
    colour = QColor('#ffffff' if active else '#263546')
    if not enabled:
        colour = QColor('#8e99a8')
    return inner.adjusted(5 * scale, 0, -5 * scale, 0), colour


class LiquidGlassMenuBar(QMenuBar):
    """Keep Qt's menu actions, mnemonics, keyboard navigation and hit testing."""
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property('menuButtonStyle') == 'classic':
            return
        painter = QPainter(self)
        painter.setClipRegion(event.region())
        # Qt owns the overflow button on narrow windows; never paint over it.
        usable = self.rect()
        for child in self.findChildren(QToolButton):
            if child.isVisible():
                usable.setRight(min(usable.right(), child.geometry().left() - 1))
        painter.setClipRect(usable, Qt.ClipOperation.IntersectClip)
        for action in self.actions():
            rect = self.actionGeometry(action)
            if not action.isVisible() or rect.isEmpty() or not usable.contains(rect):
                continue
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, action)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
            text_rect, colour = paint_liquid_glass(
                painter, QRectF(rect), '#94b7d3',
                'checked' if pressed else 'hover' if selected else 'normal', action.isEnabled())
            painter.setFont(self.font())
            painter.setPen(colour)
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextShowMnemonic
            if not self.style().styleHint(QStyle.StyleHint.SH_UnderlineShortcut, option, self):
                flags |= Qt.TextFlag.TextHideMnemonic
            painter.drawText(text_rect, flags, action.text())
        painter.end()
