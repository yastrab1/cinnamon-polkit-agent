"""Pixel-exact replica of Cinnamon's polkit AuthenticationDialog (Mint-Y-Dark-Aqua).

Geometry, colors and fonts are taken from the live Cinnamon 6.6 dialog
(St actor allocations + cinnamon.css), so everything is drawn at fixed coordinates.
"""
import math

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

W, H = 411, 355
FONT = "Ubuntu"
BASE_PT = 10.0

FG = (225, 225, 225)
DIALOG_BG = (0x22, 0x22, 0x26)
BORDER = (0x30, 0x30, 0x36)
BTN_BG = (0x30, 0x30, 0x36)
BTN_HOVER = (0x49, 0x49, 0x51)
BTN_ACTIVE = (0x3C, 0x3C, 0x44)
BTN_INSENSITIVE = (0x29, 0x29, 0x2E)
DEFAULT_BG = (0x1F, 0x9E, 0xDE)
DEFAULT_HOVER = (0x4A, 0xB2, 0xE6)
DEFAULT_ACTIVE = (0x34, 0xA8, 0xE3)
FOCUS_BTN_BORDER = (0x79, 0x79, 0x87)
FOCUS_DEFAULT_BORDER = (0xA4, 0xD8, 0xF2)
ENTRY_BG = (0x30, 0x30, 0x36)
ENTRY_FOCUS_BORDER = (112, 115, 122)
ERROR = (0xFC, 0x41, 0x38)

# allocations relative to the dialog (from Cinnamon's actor tree)
TITLE = (19, 27, 373)
DESC = (19, 66, 373)
AVATAR_ICON = (188, 129, 34)
COMBO = (157, 180, 97, 30)
ENTRY = (64, 228, 283, 32)
ENTRY_TEXT = (72, 236, 245)
EYE = (323, 236, 16)
MSG_Y = 268
CANCEL = (19, 294, 181, 42)
AUTH = (212, 294, 180, 42)

_icon_cache = {}


def rgb(c, a=1.0):
    return (c[0] / 255, c[1] / 255, c[2] / 255, a)


def font_options():
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_SUBPIXEL)
    fo.set_subpixel_order(cairo.SUBPIXEL_ORDER_RGB)
    fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
    fo.set_hint_metrics(cairo.HINT_METRICS_ON)
    return fo


def layout(cr, text, scale=1.0, weight=Pango.Weight.NORMAL, width=None, center=False):
    pl = PangoCairo.create_layout(cr)
    ctx = pl.get_context()
    PangoCairo.context_set_font_options(ctx, font_options())
    PangoCairo.context_set_resolution(ctx, 96)
    pl.context_changed()
    fd = Pango.FontDescription.from_string(FONT)
    fd.set_size(int(round(BASE_PT * scale * Pango.SCALE)))
    fd.set_weight(weight)
    pl.set_font_description(fd)
    pl.set_text(text, -1)
    if width is not None:
        pl.set_width(int(width * Pango.SCALE))
        pl.set_wrap(Pango.WrapMode.WORD_CHAR)
    if center:
        pl.set_alignment(Pango.Alignment.CENTER)
    return pl


def draw_text(cr, x, y, pl, color, alpha=1.0):
    cr.save()
    cr.set_source_rgba(*rgb(color, alpha))
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, pl)
    cr.restore()


def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def box(cr, x, y, w, h, r, bg, border, bw=1):
    rounded(cr, x, y, w, h, r)
    cr.set_source_rgba(*rgb(border))
    cr.fill()
    rounded(cr, x + bw, y + bw, w - 2 * bw, h - 2 * bw, max(r - bw, 0))
    cr.set_source_rgba(*rgb(bg))
    cr.fill()


def icon(name, size, color):
    key = (name, size, color)
    if key not in _icon_cache:
        theme = Gtk.IconTheme.get_default()
        info = theme.lookup_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        fg = Gdk.RGBA(*rgb(color))
        pb, _ = info.load_symbolic(fg, None, None, None)
        _icon_cache[key] = pb
    return _icon_cache[key]


def draw_icon(cr, name, x, y, size, color):
    pb = icon(name, size, color)
    cr.save()
    Gdk.cairo_set_source_pixbuf(cr, pb, x, y)
    cr.paint()
    cr.restore()


def button(cr, rect, label, *, insensitive=False, default=False, hover=False, active=False, focus=False):
    x, y, w, h = rect
    if insensitive:
        bg, border, fg_a = BTN_INSENSITIVE, BORDER, 0.5
    elif default:
        bg = DEFAULT_ACTIVE if active else DEFAULT_HOVER if hover else DEFAULT_BG
        border, fg_a = (FOCUS_DEFAULT_BORDER if focus else DEFAULT_BG), 1.0
    else:
        bg = BTN_ACTIVE if active else BTN_HOVER if hover else BTN_BG
        border, fg_a = (FOCUS_BTN_BORDER if focus else BTN_BG), 1.0
    box(cr, x, y, w, h, 18, bg, border)
    pl = layout(cr, label, weight=Pango.Weight.BOLD)
    _, log = pl.get_pixel_extents()
    tx = x + math.floor((w - log.width) / 2)
    ty = y + math.floor((h - log.height) / 2)
    draw_text(cr, tx, ty, pl, FG, fg_a)


def draw_dialog(cr, s):
    """s: dict with keys title, description, user, hint, password_len, caret,
    message, message_error, peek, ok_sensitive, hover, active, focus, entry_sensitive."""
    # frame
    box(cr, 0, 0, W, H, 18, DIALOG_BG, BORDER)

    # header
    pl = layout(cr, s["title"], scale=1.364, weight=Pango.Weight.ULTRABOLD, width=TITLE[2], center=True)
    draw_text(cr, TITLE[0], TITLE[1], pl, FG)
    pl = layout(cr, s["description"], width=DESC[2], center=True)
    draw_text(cr, DESC[0], DESC[1], pl, FG)

    # user
    draw_icon(cr, "xsi-avatar-default-symbolic", AVATAR_ICON[0], AVATAR_ICON[1], AVATAR_ICON[2], FG)
    cx, cy, cw, ch = COMBO
    combo_bg = (0x3A, 0x3A, 0x41) if s.get("hover") == "combo" else DIALOG_BG
    box(cr, cx, cy, cw, ch, 6, combo_bg, DIALOG_BG)
    pl = layout(cr, s["user"], weight=Pango.Weight.BOLD)
    _, log = pl.get_pixel_extents()
    draw_text(cr, cx + math.floor((cw - log.width) / 2), cy + 7, pl, FG)

    # password entry
    ex, ey, ew, eh = ENTRY
    focused = s.get("focus") == "entry"
    border = ENTRY_FOCUS_BORDER if (focused or s.get("hover") == "entry") else ENTRY_BG
    box(cr, ex, ey, ew, eh, 3, ENTRY_BG, border)
    tx, ty, tw = ENTRY_TEXT
    n = s.get("password_len", 0)
    if n:
        text = ("●" * n) if not s.get("peek") else s.get("password", "")
        pl = layout(cr, text)
        cr.save()
        cr.rectangle(tx, ty, tw, 16)
        cr.clip()
        draw_text(cr, tx, ty, pl, FG if s.get("entry_sensitive", True) else (225, 225, 225))
        cr.restore()
        caret_x = tx + pl.get_pixel_extents()[1].width
    else:
        pl = layout(cr, s.get("hint", "Password"))
        draw_text(cr, tx, ty, pl, FG, 0.3)
        caret_x = tx
    if focused and s.get("caret", True):
        cr.set_source_rgba(*rgb(FG))
        cr.rectangle(caret_x, ty, 1, 16)
        cr.fill()
    eye = "xsi-view-reveal-symbolic" if s.get("peek") else "xsi-view-conceal-symbolic"
    draw_icon(cr, eye, EYE[0], EYE[1], EYE[2], FG)

    # error / info line
    if s.get("message"):
        pl = layout(cr, s["message"], scale=0.818, width=373, center=True)
        draw_text(cr, 19, MSG_Y, pl, ERROR if s.get("message_error") else FG)

    # buttons
    button(cr, CANCEL, "Cancel", hover=s.get("hover") == "cancel",
           active=s.get("active") == "cancel", focus=s.get("focus") == "cancel")
    button(cr, AUTH, "Authenticate", insensitive=not s.get("ok_sensitive"), default=True,
           hover=s.get("hover") == "auth", active=s.get("active") == "auth", focus=s.get("focus") == "auth")


def hit(x, y):
    for name, (rx, ry, rw, rh) in (("cancel", CANCEL), ("auth", AUTH), ("entry", ENTRY), ("combo", COMBO)):
        if rx <= x < rx + rw and ry <= y < ry + rh:
            if name == "entry" and EYE[0] - 4 <= x < EYE[0] + EYE[2] + 4:
                return "eye"
            return name
    return None
