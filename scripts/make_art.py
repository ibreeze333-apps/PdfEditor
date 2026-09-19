# scripts/make_art.py — 도장 이미지(stamp1/*.png)와 앱 아이콘을 코드로 직접 그린다
"""출처를 알 수 없는 이미지를 쓰지 않기 위해, 앱에 들어가는 도장 19장과 앱 아이콘을
이 스크립트로 새로 그린다. 모든 도형·캐릭터·질감은 여기 코드가 만든 것이다.

글자는 Windows 기본 글꼴(맑은 고딕, Arial 등)로 그린 뒤 그림으로 굳힌다.

사용법:
    python scripts/make_art.py --out 미리보기폴더     # 미리보기만
    python scripts/make_art.py --install              # stamp1/, Pdf_Editor.png, logo.ico 교체
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = r'C:\Windows\Fonts'
SS = 4          # 슈퍼샘플링 배율 — 크게 그린 뒤 줄여서 선을 매끄럽게

COLORS = {
    'black': (34, 34, 38, 255),
    'blue': (31, 58, 138, 255),
    'purple': (111, 66, 160, 255),
    'brown': (140, 72, 44, 255),
    'red': (190, 38, 38, 255),
    'green': (40, 122, 64, 255),
    'navy': (32, 44, 110, 255),
}


# ── 글꼴 ──────────────────────────────────────────────────────────────
def font(names, size):
    for n in names:
        p = os.path.join(FONT_DIR, n)
        if os.path.exists(p):
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default()


KO_BOLD = ['malgunbd.ttf', 'malgun.ttf']
LATIN_HEAVY = ['ariblk.ttf', 'arialbd.ttf', 'malgunbd.ttf']
HANJA = ['malgunbd.ttf', 'malgun.ttf']


# ── 기본 도형 ─────────────────────────────────────────────────────────
def new(w, h):
    return Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0))


def finish(img, w, h, grunge=0.0, seed=0):
    if grunge > 0:
        img = rubber_texture(img, grunge, seed)
    return img.resize((w, h), Image.LANCZOS)


def ring(d, cx, cy, r, width, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=int(width))


def star(d, cx, cy, r, color, inner=0.42, rot=-90):
    pts = []
    for i in range(10):
        a = math.radians(rot + i * 36)
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def center_text(d, text, cx, cy, fnt, color):
    d.text((cx, cy), text, font=fnt, fill=color, anchor='mm')


def fit_font(names, text, max_w, start):
    size = start
    while size > 10:
        f = font(names, size)
        if f.getlength(text) <= max_w:
            return f
        size -= max(1, size // 20)
    return font(names, size)


def arc_text(img, text, cx, cy, radius, fnt, color, center_deg=-90, top=True, tracking=1.08):
    """원 둘레를 따라 글자를 놓는다. top=True 면 위쪽 호(바깥으로 선 글자)."""
    widths = [fnt.getlength(ch) * tracking for ch in text]
    total = sum(widths)
    direction = 1 if top else -1
    ang = math.radians(center_deg) - direction * (total / radius) / 2
    for ch, w in zip(text, widths):
        mid = ang + direction * (w / 2) / radius
        if ch.strip():
            size = int(fnt.size * 1.6) + 8
            tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((size / 2, size / 2), ch, font=fnt, fill=color, anchor='mm')
            rot = -(math.degrees(mid) + 90) if top else -(math.degrees(mid) - 90)
            tile = tile.rotate(rot, resample=Image.BICUBIC, expand=True)
            px = cx + radius * math.cos(mid)
            py = cy + radius * math.sin(mid)
            img.alpha_composite(tile, (int(px - tile.width / 2), int(py - tile.height / 2)))
        ang += direction * w / radius


def outline_union(img, shapes, width, color):
    """여러 도형을 합친 실루엣의 바깥선만 그린다 (겹친 안쪽 선은 생기지 않게)."""
    mask = Image.new('L', img.size, 0)
    md = ImageDraw.Draw(mask)
    for kind, box in shapes:
        if kind == 'ellipse':
            md.ellipse(box, fill=255)
        elif kind == 'rrect':
            x0, y0, x1, y1, rad = box
            md.rounded_rectangle([x0, y0, x1, y1], radius=rad, fill=255)
    m = np.array(mask)
    k = max(3, int(width) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    outer = cv2.dilate(m, kernel)
    inner = cv2.erode(m, kernel)
    line = (outer > 127) & (inner < 128)
    arr = np.array(img)
    arr[line] = color
    return Image.fromarray(arr, 'RGBA')


def rubber_texture(img, strength, seed):
    """고무도장처럼 잉크가 군데군데 빠진 질감 (무작위 잡음으로 직접 생성)."""
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    rng = np.random.default_rng(seed)
    coarse = rng.random((h // 24 + 2, w // 24 + 2)).astype(np.float32)
    coarse = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)
    fine = rng.random((h, w)).astype(np.float32)
    fine = cv2.GaussianBlur(fine, (0, 0), 1.2 * SS)
    fine = (fine - fine.min()) / (fine.max() - fine.min() + 1e-6)
    noise = 0.65 * coarse + 0.35 * fine
    keep = np.clip((noise - strength) / 0.10, 0.0, 1.0)
    specks = rng.random((h, w)) < 0.004 * strength * 10
    specks = cv2.dilate(specks.astype(np.uint8), np.ones((SS, SS), np.uint8)) > 0
    alpha = arr[..., 3] * keep
    alpha[specks] = 0
    arr[..., 3] = alpha
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')


# ── 캐릭터 ────────────────────────────────────────────────────────────
def draw_kids(img, cx, cy, r, color, lw):
    """모자 쓴 남자아이 + 양갈래 머리 여자아이."""
    d = ImageDraw.Draw(img)
    fr = r * 0.42
    bx, gx = cx - r * 0.43, cx + r * 0.43
    y = cy + r * 0.06
    img = outline_union(img, [('ellipse', [bx - fr, y - fr, bx + fr, y + fr]),
                              ('ellipse', [gx - fr, y - fr, gx + fr, y + fr])], lw, color)
    d = ImageDraw.Draw(img)
    # 남자아이 모자 (챙은 바깥쪽 왼편으로)
    d.chord([bx - fr * 1.02, y - fr * 1.10, bx + fr * 1.02, y + fr * 0.30], 180, 360, fill=color)
    d.rounded_rectangle([bx - fr * 1.30, y - fr * 0.52, bx + fr * 0.10, y - fr * 0.30], radius=fr * 0.10, fill=color)
    d.ellipse([bx - fr * 0.12, y - fr * 1.22, bx + fr * 0.12, y - fr * 0.98], fill=color)
    # 여자아이 앞머리 + 양쪽 묶음 머리 + 리본
    d.chord([gx - fr * 1.02, y - fr * 1.06, gx + fr * 1.02, y + fr * 0.10], 180, 360, fill=color)
    for s in (-1, 1):
        ox = gx + s * fr * 1.12
        d.ellipse([ox - fr * 0.30, y - fr * 0.55, ox + fr * 0.30, y + fr * 0.05], fill=color)
    d.polygon([(gx - fr * 0.05, y - fr * 1.00), (gx - fr * 0.38, y - fr * 1.22), (gx - fr * 0.38, y - fr * 0.80)], fill=color)
    d.polygon([(gx + fr * 0.05, y - fr * 1.00), (gx + fr * 0.38, y - fr * 1.22), (gx + fr * 0.38, y - fr * 0.80)], fill=color)
    # 얼굴
    er = fr * 0.085
    for fx in (bx, gx):
        for s in (-1, 1):
            ex, ey = fx + s * fr * 0.33, y + fr * 0.05
            d.ellipse([ex - er, ey - er * 1.25, ex + er, ey + er * 1.25], fill=color)
        d.arc([fx - fr * 0.30, y + fr * 0.10, fx + fr * 0.30, y + fr * 0.62], 20, 160, fill=color, width=int(lw * 0.8))
        for s in (-1, 1):
            cxh = fx + s * fr * 0.58
            d.line([cxh - fr * 0.10, y + fr * 0.28, cxh + fr * 0.10, y + fr * 0.20], fill=color, width=int(lw * 0.5))
    return img


def draw_hamster(img, cx, cy, r, color, lw):
    """볼주머니가 볼록한 햄스터 얼굴."""
    head_w, head_h = r * 1.00, r * 0.80
    ear = r * 0.24
    cheek = r * 0.36
    shapes = [
        ('ellipse', [cx - head_w, cy - head_h, cx + head_w, cy + head_h]),
        ('ellipse', [cx - r * 0.78 - ear, cy - r * 0.70 - ear, cx - r * 0.78 + ear, cy - r * 0.70 + ear]),
        ('ellipse', [cx + r * 0.78 - ear, cy - r * 0.70 - ear, cx + r * 0.78 + ear, cy - r * 0.70 + ear]),
        ('ellipse', [cx - r * 0.80 - cheek, cy + r * 0.22 - cheek, cx - r * 0.80 + cheek, cy + r * 0.22 + cheek]),
        ('ellipse', [cx + r * 0.80 - cheek, cy + r * 0.22 - cheek, cx + r * 0.80 + cheek, cy + r * 0.22 + cheek]),
    ]
    img = outline_union(img, shapes, lw, color)
    d = ImageDraw.Draw(img)
    for s in (-1, 1):                                   # 귀 안쪽
        ex = cx + s * r * 0.78
        d.ellipse([ex - ear * 0.45, cy - r * 0.70 - ear * 0.45, ex + ear * 0.45, cy - r * 0.70 + ear * 0.45], fill=color)
    for dx in (-0.16, 0.0, 0.16):                       # 이마 줄무늬
        d.line([cx + r * dx, cy - r * 0.66, cx + r * dx, cy - r * 0.44], fill=color, width=int(lw * 0.8))
    er = r * 0.085
    for s in (-1, 1):                                   # 눈 + 반짝
        ex, ey = cx + s * r * 0.36, cy - r * 0.10
        d.ellipse([ex - er, ey - er * 1.2, ex + er, ey + er * 1.2], fill=color)
        d.ellipse([ex - er * 0.35 + er * 0.25, ey - er * 0.75, ex + er * 0.05 + er * 0.25, ey - er * 0.35], fill=(0, 0, 0, 0))
    d.polygon([(cx - r * 0.08, cy + r * 0.10), (cx + r * 0.08, cy + r * 0.10), (cx, cy + r * 0.20)], fill=color)
    d.arc([cx - r * 0.16, cy + r * 0.10, cx, cy + r * 0.32], 0, 150, fill=color, width=int(lw * 0.7))
    d.arc([cx, cy + r * 0.10, cx + r * 0.16, cy + r * 0.32], 30, 180, fill=color, width=int(lw * 0.7))
    for s in (-1, 1):                                   # 볼 터치
        bx = cx + s * r * 0.80
        for k in (-1, 0, 1):
            d.line([bx + k * r * 0.07 - r * 0.03, cy + r * 0.30, bx + k * r * 0.07 + r * 0.03, cy + r * 0.20],
                   fill=color, width=int(lw * 0.5))
    return img


def draw_rabbit(img, cx, cy, r, color, lw):
    """긴 귀가 선 토끼 얼굴."""
    head_w, head_h = r * 0.92, r * 0.78
    hy = cy + r * 0.28
    ew, eh = r * 0.24, r * 0.78
    shapes = [('ellipse', [cx - head_w, hy - head_h, cx + head_w, hy + head_h])]
    ear_boxes = []
    for s in (-1, 1):
        ex = cx + s * r * 0.40
        box = (ex - ew, hy - head_h - eh * 1.25, ex + ew, hy - head_h * 0.35, ew)
        ear_boxes.append(box)
        shapes.append(('rrect', box))
    img = outline_union(img, shapes, lw, color)
    d = ImageDraw.Draw(img)
    for (x0, y0, x1, y1, rad) in ear_boxes:             # 귀 안쪽
        ix = (x1 - x0) * 0.28
        d.rounded_rectangle([x0 + ix, y0 + r * 0.14, x1 - ix, y1 - r * 0.30], radius=rad * 0.5,
                            outline=color, width=int(lw * 0.6))
    er = r * 0.085
    for s in (-1, 1):
        ex, ey = cx + s * r * 0.34, hy - r * 0.05
        d.ellipse([ex - er, ey - er * 1.2, ex + er, ey + er * 1.2], fill=color)
        bx = cx + s * r * 0.58
        d.ellipse([bx - r * 0.12, hy + r * 0.16, bx + r * 0.12, hy + r * 0.28], outline=color, width=int(lw * 0.5))
    d.ellipse([cx - r * 0.08, hy + r * 0.06, cx + r * 0.08, hy + r * 0.16], fill=color)
    d.line([cx, hy + r * 0.16, cx, hy + r * 0.26], fill=color, width=int(lw * 0.6))
    d.arc([cx - r * 0.18, hy + r * 0.14, cx, hy + r * 0.38], 0, 160, fill=color, width=int(lw * 0.7))
    d.arc([cx, hy + r * 0.14, cx + r * 0.18, hy + r * 0.38], 20, 180, fill=color, width=int(lw * 0.7))
    return img


# ── 도장 ─────────────────────────────────────────────────────────────
def stamp_kids(color, seed):
    W = H = 500
    img = new(W, H)
    c, R = W * SS / 2, W * SS * 0.46
    lw = W * SS * 0.022
    d = ImageDraw.Draw(img)
    ring(d, c, c, R, lw, color)
    ring(d, c, c, R * 0.93, lw * 0.35, color)
    arc_text(img, '참! 잘했어요', c, c, R * 0.75, font(KO_BOLD, W * SS * 0.10), color)
    img = draw_kids(img, c + R * 0.04, c + R * 0.08, R * 0.66, color, lw * 0.85)
    d = ImageDraw.Draw(img)
    for i, off in enumerate((-0.30, -0.15, 0.0, 0.15, 0.30)):
        star(d, c + R * off * 1.1, c + R * 0.72 - (0.05 * R if i == 2 else 0), R * 0.075, color)
    return finish(img, W, H, 0.10, seed)


def stamp_animal(kind, text, color, seed):
    W = H = 500
    img = new(W, H)
    c, R = W * SS / 2, W * SS * 0.46
    lw = W * SS * 0.022
    d = ImageDraw.Draw(img)
    ring(d, c, c, R, lw, color)
    if kind == 'hamster':
        img = draw_hamster(img, c, c - R * 0.16, R * 0.44, color, lw * 0.8)
    else:
        img = draw_rabbit(img, c, c - R * 0.22, R * 0.40, color, lw * 0.8)
    d = ImageDraw.Draw(img)
    center_text(d, text, c, c + R * 0.56, fit_font(KO_BOLD, text, R * 1.30, W * SS * 0.11), color)
    return finish(img, W, H, 0.10, seed)


def knockout_band(img, text, cx, cy, bw, bh, angle, color, fnt, border=True):
    """색 띠 위에 글자를 '빼서'(투명) 새긴 뒤 기울여 얹는다."""
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    ld.rectangle([x0, y0, x1, y1], fill=color)
    if border:
        g = bh * 0.10
        ld.rectangle([x0 + g, y0 + g, x1 - g, y1 - g], outline=(0, 0, 0, 0), width=int(bh * 0.04))
    tmask = Image.new('L', img.size, 0)
    ImageDraw.Draw(tmask).text((cx, cy), text, font=fnt, fill=255, anchor='mm')
    arr = np.array(layer)
    arr[np.array(tmask) > 127, 3] = 0
    layer = Image.fromarray(arr, 'RGBA').rotate(angle, resample=Image.BICUBIC, center=(cx, cy))
    img.alpha_composite(layer)
    return img


def stamp_fitness(variant, color, seed):
    if variant == 'bar':                               # 13: 기울어진 띠
        W, H = 580, 430
        img = new(W, H)
        cx, cy = W * SS / 2, H * SS / 2
        f = fit_font(LATIN_HEAVY, 'FITNESS', W * SS * 0.66, H * SS * 0.24)
        img = knockout_band(img, 'FITNESS', cx, cy, W * SS * 0.80, H * SS * 0.32, 12, color, f)
        return finish(img, W, H, 0.22, seed)
    W = H = 500
    img = new(W, H)
    c, R = W * SS / 2, W * SS * 0.42
    lw = W * SS * 0.020
    d = ImageDraw.Draw(img)
    ring(d, c, c, R, lw, color)
    ring(d, c, c, R * 0.86, lw * 0.6, color)
    if variant == 'approved':                          # 15
        arc_text(img, 'APPROVED', c, c, R * 0.70, font(LATIN_HEAVY, W * SS * 0.075), color, center_deg=90, top=False, tracking=1.25)
        for k in range(7):
            a = math.radians(-150 + k * 20)
            star(d, c + R * 0.70 * math.cos(a), c + R * 0.70 * math.sin(a), R * 0.05, color)
    else:                                              # 14, 16
        for k in range(10):
            a = math.radians(-90 + k * 36)
            star(d, c + R * 0.93 * math.cos(a), c + R * 0.93 * math.sin(a), R * 0.045, color)
    f = fit_font(LATIN_HEAVY, 'FITNESS', R * 1.45, W * SS * 0.14)
    img = knockout_band(img, 'FITNESS', c, c, R * 2.05, R * 0.50, 14 if variant != 'approved' else 8, color, f)
    return finish(img, W, H, 0.20 if variant != 'approved' else 0.16, seed)


def stamp_postbox(color, seed):
    W, H = 440, 330
    img = new(W, H)
    d = ImageDraw.Draw(img)
    S = SS
    cx, cy, R = W * S * 0.68, H * S * 0.50, H * S * 0.40
    lw = W * S * 0.012
    ring(d, cx, cy, R, lw, color)
    ring(d, cx, cy, R * 0.62, lw * 0.6, color)
    arc_text(img, 'POST BOX', cx, cy, R * 0.81, font(LATIN_HEAVY, H * S * 0.075), color, tracking=1.15)
    arc_text(img, '* MAIL *', cx, cy, R * 0.81, font(LATIN_HEAVY, H * S * 0.06), color, center_deg=90, top=False, tracking=1.2)
    center_text(d, '★', cx, cy + R * 0.10, font(['seguisym.ttf', 'malgunbd.ttf'], H * S * 0.16), color)
    for k in range(4):                                 # 소인 물결선
        y = H * S * (0.26 + k * 0.10)
        pts = [(x, y + math.sin(x / (W * S * 0.05)) * H * S * 0.025) for x in np.linspace(W * S * 0.04, cx - R * 0.2, 60)]
        d.line(pts, fill=color, width=int(lw * 0.8), joint='curve')
    for k in range(9):                                 # 아래 빗금 띠
        x = W * S * (0.08 + k * 0.035)
        d.line([x, H * S * 0.82, x + W * S * 0.02, H * S * 0.72], fill=color, width=int(lw * 0.7))
    return finish(img, W, H, 0.12, seed)


def stamp_hanja(color, seed):
    W, H = 260, 360
    img = new(W, H)
    d = ImageDraw.Draw(img)
    S = SS
    m = W * S * 0.07
    d.rounded_rectangle([m, m, W * S - m, H * S - m], radius=W * S * 0.08, outline=color, width=int(W * S * 0.05))
    d.rounded_rectangle([m * 1.9, m * 1.9, W * S - m * 1.9, H * S - m * 1.9], radius=W * S * 0.05,
                        outline=color, width=int(W * S * 0.015))
    f = font(HANJA, H * S * 0.30)
    center_text(d, '元', W * S / 2, H * S * 0.33, f, color)
    center_text(d, '旦', W * S / 2, H * S * 0.69, f, color)
    return finish(img, W, H, 0.18, seed)


def stamp_perfect(color, seed):
    W, H = 300, 400
    img = new(W, H)
    d = ImageDraw.Draw(img)
    S = SS
    c = (W * S / 2, H * S / 2)
    R = W * S * 0.40
    lw = W * S * 0.022
    ring(d, c[0], c[1], R, lw, color)
    ring(d, c[0], c[1], R * 0.87, lw * 0.5, color)
    for k in range(5):
        a = math.radians(-130 + k * 20)
        star(d, c[0] + R * 0.70 * math.cos(a), c[1] + R * 0.70 * math.sin(a), R * 0.07, color)
        a2 = math.radians(50 + k * 20)
        star(d, c[0] + R * 0.70 * math.cos(a2), c[1] + R * 0.70 * math.sin(a2), R * 0.07, color)
    f = fit_font(LATIN_HEAVY, 'PERFECT', R * 1.55, W * S * 0.17)
    img = knockout_band(img, 'PERFECT', c[0], c[1], R * 2.10, R * 0.48, 20, color, f)
    return finish(img, W, H, 0.18, seed)


STAMPS = [
    (1, lambda: stamp_kids(COLORS['black'], 1)),
    (2, lambda: stamp_kids(COLORS['blue'], 2)),
    (3, lambda: stamp_kids(COLORS['purple'], 3)),
    (4, lambda: stamp_kids(COLORS['brown'], 4)),
    (5, lambda: stamp_animal('hamster', '훌륭해!', COLORS['red'], 5)),
    (6, lambda: stamp_animal('hamster', '대단해!', COLORS['red'], 6)),
    (7, lambda: stamp_animal('hamster', '놀라워!', COLORS['red'], 7)),
    (8, lambda: stamp_animal('hamster', '최고야!', COLORS['red'], 8)),
    (9, lambda: stamp_animal('rabbit', '칭찬해요!', COLORS['red'], 9)),
    (10, lambda: stamp_animal('rabbit', '참잘했어요', COLORS['red'], 10)),
    (11, lambda: stamp_animal('rabbit', '완전 멋져!', COLORS['red'], 11)),
    (12, lambda: stamp_animal('rabbit', '굉장해!', COLORS['red'], 12)),
    (13, lambda: stamp_fitness('bar', COLORS['navy'], 13)),
    (14, lambda: stamp_fitness('round', COLORS['red'], 14)),
    (15, lambda: stamp_fitness('approved', COLORS['green'], 15)),
    (16, lambda: stamp_fitness('round', COLORS['black'], 16)),
    (17, lambda: stamp_postbox(COLORS['black'], 17)),
    (18, lambda: stamp_hanja(COLORS['red'], 18)),
    (19, lambda: stamp_perfect(COLORS['red'], 19)),
]


# ── 앱 아이콘 ─────────────────────────────────────────────────────────
def app_icon(size=1024):
    """접힌 모서리 문서 + 빨간 PDF 띠 + 연필."""
    S = size
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    # 그림자
    sh = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([S * 0.17, S * 0.10, S * 0.77, S * 0.93], radius=S * 0.05, fill=(0, 0, 0, 70))
    sh = Image.fromarray(cv2.GaussianBlur(np.array(sh), (0, 0), S * 0.018))
    img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = S * 0.14, S * 0.06, S * 0.74, S * 0.89
    fold = S * 0.17
    page = [(x0 + S * 0.04, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1 - S * 0.04),
            (x1 - S * 0.04, y1), (x0 + S * 0.04, y1), (x0, y1 - S * 0.04), (x0, y0 + S * 0.04)]
    d.polygon(page, fill=(255, 255, 255, 255))
    d.line(page + [page[0]], fill=(150, 160, 178, 255), width=int(S * 0.012), joint='curve')
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(214, 221, 233, 255))
    d.line([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(150, 160, 178, 255), width=int(S * 0.010))
    for k in range(5):                                  # 본문 줄
        y = y0 + S * (0.24 + k * 0.075)
        d.rounded_rectangle([x0 + S * 0.08, y, x1 - S * (0.08 if k % 2 == 0 else 0.20), y + S * 0.028],
                            radius=S * 0.014, fill=(193, 203, 220, 255))
    band = [x0 - S * 0.06, y1 - S * 0.27, x0 + S * 0.38, y1 - S * 0.11]
    d.rounded_rectangle(band, radius=S * 0.035, fill=(214, 45, 48, 255))
    center_text(d, 'PDF', (band[0] + band[2]) / 2, (band[1] + band[3]) / 2,
                font(['arialbd.ttf', 'malgunbd.ttf'], S * 0.12), (255, 255, 255, 255))
    # 연필 (오른쪽 아래에서 왼쪽 위로)
    pen = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pen)
    L, Wd = S * 0.62, S * 0.115
    px0, py = S * 0.30, S * 0.50
    body = [px0 + L * 0.20, py - Wd / 2, px0 + L * 0.84, py + Wd / 2]
    pd.rectangle(body, fill=(247, 190, 44, 255))
    pd.rectangle([body[0], py - Wd / 2, body[2], py - Wd / 6], fill=(252, 214, 96, 255))
    pd.rectangle([body[0], py + Wd / 6, body[2], py + Wd / 2], fill=(223, 160, 26, 255))
    pd.rectangle([px0 + L * 0.84, py - Wd / 2, px0 + L * 0.90, py + Wd / 2], fill=(176, 184, 196, 255))
    pd.rounded_rectangle([px0 + L * 0.90, py - Wd / 2, px0 + L * 1.00, py + Wd / 2], radius=Wd * 0.25, fill=(240, 128, 150, 255))
    pd.polygon([(px0 + L * 0.20, py - Wd / 2), (px0 + L * 0.20, py + Wd / 2), (px0, py)], fill=(238, 206, 160, 255))
    pd.polygon([(px0 + L * 0.07, py - Wd * 0.17), (px0 + L * 0.07, py + Wd * 0.17), (px0, py)], fill=(52, 52, 60, 255))
    pen = pen.rotate(40, resample=Image.BICUBIC, center=(S * 0.62, S * 0.50), translate=(S * 0.06, S * 0.10))
    psh = Image.fromarray(cv2.GaussianBlur(np.array(pen)[..., 3], (0, 0), S * 0.012))
    shadow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    shadow.putalpha(psh.point(lambda v: int(v * 0.35)))
    img.alpha_composite(shadow, (int(S * 0.012), int(S * 0.018)))
    img.alpha_composite(pen)
    return img


ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help='미리보기 폴더 (앱 파일은 건드리지 않음)')
    ap.add_argument('--install', action='store_true', help='stamp1/, Pdf_Editor.png, logo.ico 를 교체')
    a = ap.parse_args()
    if not a.out and not a.install:
        ap.error('--out 또는 --install 중 하나를 지정하세요')
    out = a.out or os.path.join(ROOT, 'stamp1')
    os.makedirs(out, exist_ok=True)
    for n, make in STAMPS:
        make().save(os.path.join(out, f'{n}.png'), optimize=True)
    icon = app_icon(1024)
    icon_png = os.path.join(out if a.out else ROOT, 'Pdf_Editor.png')
    icon.resize((256, 256), Image.LANCZOS).save(icon_png, optimize=True)
    ico_path = os.path.join(out if a.out else ROOT, 'logo.ico')
    icon.save(ico_path, format='ICO', sizes=[(s, s) for s in ICO_SIZES])
    print('완료:', out)


if __name__ == '__main__':
    sys.exit(main())
