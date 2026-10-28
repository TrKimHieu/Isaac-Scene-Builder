"""
ui_kit.py - Small drawing kit for the pygame editors ("Ivory & Ink" theme in config.py).

Fonts (Segoe UI family, Arial fallback) and a handful of components drawn the same way in
scene_editor.py and shape_editor.py: cards with a soft shadow, outlined buttons whose active
state is an ink fill, uppercase section captions with letter-spacing, pills, text fields.
"""
import pygame

from config import (PANEL_BG, BORDER, BTN, BTN_HOVER, BTN_ACTIVE, ON_ACTIVE, TEXT, TEXT_DIM,
                    ACCENT, ACCENT_DIM, FIELD_BG, FIELD_ACTIVE_BG, DANGER, SHADOW_ALPHA)

RADIUS = 8
HINT = (178, 170, 156)          # keyboard hint inside a button
HINT_ON_ACTIVE = (150, 146, 138)

_FAMILIES = {
    "regular": "segoeui,arial",
    "semibold": "segoeuisemibold,segoeui,arial",
    "light": "segoeuisemilight,segoeui,arial",
    "mono": "cascadiamono,consolas,couriernew",
}


def fonts():
    """Font set used by both editors."""
    def f(family, size, bold=False):
        return pygame.font.SysFont(_FAMILIES[family], size, bold=bold)
    return {
        "title": f("semibold", 19),
        "subtitle": f("regular", 12),
        "body": f("regular", 14),
        "small": f("regular", 13),
        "caption": f("semibold", 11),
        "button": f("regular", 13),
        "mono": f("mono", 13),
        "big": f("semibold", 34),
    }


def text(screen, s, pos, font, color=TEXT, center=False):
    surf = font.render(s, True, color)
    if center:
        pos = (pos[0] - surf.get_width() // 2, pos[1] - surf.get_height() // 2)
    screen.blit(surf, pos)
    return surf.get_width()


def tracked(screen, s, pos, font, color=TEXT_DIM, spacing=1.6):
    """Letter-spaced uppercase caption (SECTION TITLES)."""
    x, y = pos
    for ch in s.upper():
        surf = font.render(ch, True, color)
        screen.blit(surf, (x, y))
        x += surf.get_width() + spacing
    return x - pos[0]


def shadow(screen, rect, radius=RADIUS, spread=6, alpha=SHADOW_ALPHA):
    """Soft drop shadow under a rect (a few stacked translucent rounded rects)."""
    layer = pygame.Surface((rect.w + 2 * spread, rect.h + 2 * spread), pygame.SRCALPHA)
    for k in range(spread, 0, -2):
        a = int(alpha * (1 - k / float(spread + 1)) / 2)
        pygame.draw.rect(layer, (40, 32, 20, a),
                         pygame.Rect(spread - k, spread - k + 2, rect.w + 2 * k, rect.h + 2 * k),
                         border_radius=radius + k)
    screen.blit(layer, (rect.x - spread, rect.y - spread))


def card(screen, rect, fill=PANEL_BG, border=BORDER, radius=RADIUS, with_shadow=True):
    if with_shadow:
        shadow(screen, rect, radius)
    pygame.draw.rect(screen, fill, rect, border_radius=radius)
    if border:
        pygame.draw.rect(screen, border, rect, 1, border_radius=radius)


def button(screen, rect, label, font, active=False, hover=False, danger=False, align="left"):
    """Outlined button; active = ink fill with ivory text; danger = red text."""
    if active:
        fill, border, fg = BTN_ACTIVE, BTN_ACTIVE, ON_ACTIVE
    else:
        fill = BTN_HOVER if hover else BTN
        border = (DANGER if (danger and hover) else BORDER)
        fg = DANGER if danger else TEXT
    pygame.draw.rect(screen, fill, rect, border_radius=RADIUS)
    pygame.draw.rect(screen, border, rect, 1, border_radius=RADIUS)
    label, _, hint = label.partition("	")          # "Undo	Ctrl+Z": hint right-aligned
    surf = font.render(label, True, fg)
    y = rect.y + (rect.h - surf.get_height()) // 2
    x = rect.x + 12 if align == "left" else rect.x + (rect.w - surf.get_width()) // 2
    screen.blit(surf, (x, y))
    if hint:
        hs = font.render(hint, True, HINT_ON_ACTIVE if active else HINT)
        screen.blit(hs, (rect.right - 12 - hs.get_width(), rect.y + (rect.h - hs.get_height()) // 2))


def pill(screen, rect, label, font, active=False, hover=False):
    """Rounded tab / chip."""
    r = rect.h // 2
    if active:
        pygame.draw.rect(screen, BTN_ACTIVE, rect, border_radius=r)
        fg = ON_ACTIVE
    else:
        pygame.draw.rect(screen, BTN_HOVER if hover else BTN, rect, border_radius=r)
        pygame.draw.rect(screen, BORDER, rect, 1, border_radius=r)
        fg = TEXT if hover else TEXT_DIM
    surf = font.render(label, True, fg)
    screen.blit(surf, (rect.x + (rect.w - surf.get_width()) // 2,
                       rect.y + (rect.h - surf.get_height()) // 2))


def pill_width(label, font, pad=12):
    return font.size(label)[0] + 2 * pad


def field(screen, rect, value, font, active=False, placeholder=False):
    """Text field: white with hairline border, gold focus ring."""
    pygame.draw.rect(screen, FIELD_ACTIVE_BG if active else FIELD_BG, rect, border_radius=6)
    pygame.draw.rect(screen, ACCENT if active else BORDER, rect, 1, border_radius=6)
    surf = font.render(value, True, TEXT_DIM if placeholder else TEXT)
    screen.blit(surf, (rect.x + 10, rect.y + (rect.h - surf.get_height()) // 2))


def selected_row(screen, rect):
    """Champagne-tinted row with a gold bar on the left."""
    pygame.draw.rect(screen, ACCENT_DIM, rect, border_radius=6)
    pygame.draw.rect(screen, ACCENT, pygame.Rect(rect.x, rect.y + 3, 3, rect.h - 6), border_radius=2)
