"""Build print-ready Leadzo business card PDFs (front + back, separate files).

Spec (from the printer):
  artwork 3.7 x 2.2 in incl. bleed, trim 3.5 x 2 in, safe area 5 mm inside trim,
  CMYK, text converted to outlines, min 8 pt text, vector QR supplied separately.

Usage: python3 build_card.py   (writes into ./output)
Requires: reportlab, fonttools, uharfbuzz, segno
"""
import io
import math
import os

import segno
import uharfbuzz as hb
from fontTools.pens.basePen import BasePen
from fontTools.pens.transformPen import TransformPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from reportlab.lib.colors import CMYKColor, Color
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

# ---------------------------------------------------------------- geometry
INCH = 72.0
BLEED = 0.1 * INCH                       # 0.1 in each side -> 3.7 x 2.2 in
TRIM_W, TRIM_H = 3.5 * INCH, 2.0 * INCH
PAGE_W, PAGE_H = TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED
SAFE = 5 / 25.4 * INCH                   # 5 mm

# The layout is measured from the approved mock-up in "reference px"
# (740 px across the 3.5 in trim). X and sizes use S; Y uses SY.
S = TRIM_W / 740.0
SY = TRIM_H / 430.0


def X(px):
    return BLEED + px * S


def Y(px):  # reference y is top-down
    return BLEED + TRIM_H - px * SY


# ---------------------------------------------------------------- colours
# Hex values are sampled from the approved design. In CMYK mode each one is
# converted with the plain RGB->CMYK formula; QR black is forced to K-only.
PALETTE = {
    "BLUE": "#0166FB",         # brand blue (stripe, logo, back background)
    "BLUE_DOT": "#4A90FF",     # back-side dot pattern (max)
    "BLUE_STRIPE": "#B0CFFC",  # back-side right edge stripe
    "LOGO_TINT": "#D3E4FF",    # light "L" inside the logo mark
    "NAVY": "#1E2B4F",         # name / contact text
    "FRAME": "#E3EAF6",        # faint concentric frames on front
    "WHITE": "#FFFFFF",
}
MODE = "cmyk"


def color(hexstr):
    r, g, b = (int(hexstr[i:i + 2], 16) / 255 for i in (1, 3, 5))
    if MODE == "rgb":
        return Color(r, g, b)
    k = 1 - max(r, g, b)
    if k >= 1:
        return CMYKColor(0, 0, 0, 1)
    return CMYKColor(*(round((1 - v - k) / (1 - k), 3) for v in (r, g, b)), round(k, 3))


def set_mode(mode):
    global MODE, BLACK
    MODE = mode
    for name, hexstr in PALETTE.items():
        globals()[name] = color(hexstr)
    BLACK = CMYKColor(0, 0, 0, 1) if mode == "cmyk" else Color(0, 0, 0)  # QR modules


set_mode("cmyk")

QR_URL = "https://leadzo.co.in/professionals/join"


def mix(a, b, t):
    if MODE == "rgb":
        return Color(*[x + (y - x) * t for x, y in zip(a.rgb(), b.rgb())])
    return CMYKColor(*[a_ + (b_ - a_) * t for a_, b_ in zip(
        (a.cyan, a.magenta, a.yellow, a.black), (b.cyan, b.magenta, b.yellow, b.black))])


# ---------------------------------------------------------------- outlined text
class RLPen(BasePen):
    def __init__(self, path):
        super().__init__(None)
        self.p = path

    def _moveTo(self, pt):
        self.p.moveTo(*pt)

    def _lineTo(self, pt):
        self.p.lineTo(*pt)

    def _curveToOne(self, p1, p2, p3):
        self.p.curveTo(*p1, *p2, *p3)

    def _closePath(self):
        self.p.close()

    def _endPath(self):
        pass


class Font:
    def __init__(self, weight, family="plus-jakarta-sans"):
        tt = TTFont(os.path.join(HERE, "fonts", f"{family}-latin-{weight}-normal.woff"))
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        self.tt = TTFont(io.BytesIO(buf.getvalue()))
        self.hbfont = hb.Font(hb.Face(hb.Blob(buf.getvalue())))
        self.upm = self.tt["head"].unitsPerEm
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()

    def shape(self, text):
        b = hb.Buffer()
        b.add_str(text)
        b.guess_segment_properties()
        hb.shape(self.hbfont, b, {"kern": True, "liga": True})
        return b.glyph_infos, b.glyph_positions

    def width(self, text, size, tracking=0.0):
        _, pos = self.shape(text)
        return sum(p.x_advance for p in pos) * size / self.upm + tracking * size * (len(pos) - 1)

    def draw(self, c, text, size, x, y, color, tracking=0.0, align="left"):
        """Draw `text` as filled vector outlines (no live font in the PDF)."""
        w = self.width(text, size, tracking)
        if align == "right":
            x -= w
        elif align == "center":
            x -= w / 2
        infos, pos = self.shape(text)
        sc = size / self.upm
        path = c.beginPath()
        pen = RLPen(path)
        cx = 0.0
        for info, p in zip(infos, pos):
            name = self.order[info.codepoint]
            tp = TransformPen(pen, (sc, 0, 0, sc, x + (cx + p.x_offset) * sc, y + p.y_offset * sc))
            self.glyphs[name].draw(tp)
            cx += p.x_advance + tracking * self.upm
        c.setFillColor(color)
        c.drawPath(path, stroke=0, fill=1, fillMode=1)  # non-zero winding
        return w

    def fit(self, text, width_pt):
        return width_pt / self.width(text, 1.0)


MEDIUM, SEMIBOLD, BOLD = Font(500), Font(600), Font(700)
WORDMARK = Font(700, "quicksand")  # closest match to the Leadzo wordmark

# ---------------------------------------------------------------- icons (Lucide, 24x24, stroke 2)
ICONS = {
    "phone": ["M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2"
              "A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233"
              " 14 14 0 0 0 6.392 6.384"],
    "mail": ["m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7",
             "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"],
    "globe": ["M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20z",
              "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20", "M2 12h20"],
}


def draw_icon(c, name, cx, cy, size, color):
    c.saveState()
    k = size / 24.0
    c.translate(cx - size / 2, cy + size / 2)
    c.scale(k, -k)
    c.setStrokeColor(color)
    c.setLineWidth(2)
    c.setLineCap(1)
    c.setLineJoin(1)
    for d in ICONS[name]:
        p = c.beginPath()
        parse_path(d, RLPen(p))
        c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


# ---------------------------------------------------------------- page helpers
def new_page(path):
    c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Leadzo business card")
    c.setAuthor("Leadzo")
    trim = (BLEED, BLEED, BLEED + TRIM_W, BLEED + TRIM_H)
    c.setTrimBox(trim)
    c.setBleedBox((0, 0, PAGE_W, PAGE_H))
    c.setArtBox(trim)
    return c


def fill_rect(c, x, y, w, h, color, r=0):
    c.setFillColor(color)
    if r:
        c.roundRect(x, y, w, h, r, stroke=0, fill=1)
    else:
        c.rect(x, y, w, h, stroke=0, fill=1)


# ---------------------------------------------------------------- front
def build_front(path):
    c = new_page(path)
    fill_rect(c, 0, 0, PAGE_W, PAGE_H, WHITE)

    # faint concentric rounded frames, bottom-right, running off into the bleed
    c.setStrokeColor(FRAME)
    c.setLineWidth(2 * S)
    for x0, y0, r in ((506, 185, 70), (583, 258, 60), (658, 332, 50)):
        x, y = X(x0), Y(y0)
        p = c.beginPath()
        p.moveTo(x, -5)
        p.lineTo(x, y - r * S)
        p.arcTo(x, y - 2 * r * S, x + 2 * r * S, y, startAng=180, extent=-90)
        p.lineTo(PAGE_W + 5, y)
        c.drawPath(p, stroke=1, fill=0)

    # left brand stripe (into bleed)
    fill_rect(c, 0, 0, X(28), PAGE_H, BLUE)

    # logo mark
    ix, iy, isz = X(65), Y(120), 52 * S
    fill_rect(c, ix, iy, isz, isz, BLUE, r=12 * S)
    u = isz / 52.0

    def bracket(pts, col):  # thick rounded stroke, coordinates top-down in a 52-unit box
        c.setStrokeColor(col)
        c.setLineWidth(7 * u)
        c.setLineCap(1)
        c.setLineJoin(1)
        p = c.beginPath()
        p.moveTo(ix + pts[0][0] * u, iy + isz - pts[0][1] * u)
        for px_, py_ in pts[1:]:
            p.lineTo(ix + px_ * u, iy + isz - py_ * u)
        c.drawPath(p, stroke=1, fill=0)

    bracket([(16, 17), (16, 36), (29, 36)], LOGO_TINT)   # lower-left "L"
    bracket([(24, 16), (36, 16), (36, 27)], WHITE)       # upper-right corner

    # wordmark
    WORDMARK.draw(c, "Leadzo", WORDMARK.fit("Leadzo", 170 * S), X(130), Y(115), BLUE)

    # name + title
    BOLD.draw(c, "Rakshit Honakeri", BOLD.fit("Rakshit Honakeri", 338 * S), X(65), Y(190), NAVY)
    MEDIUM.draw(c, "Sales Head", 9.0, X(65), Y(227), BLUE)

    # contacts
    size = 8.5
    rows = (("phone", "+91 81237 93546", 282), ("mail", "rakshit@leadzo.co.in", 319),
            ("globe", "www.leadzo.co.in", 356))
    for icon, text, base in rows:
        draw_icon(c, icon, X(77), Y(base) + size * 0.36, 23 * S, BLUE)
        MEDIUM.draw(c, text, size, X(110), Y(base), NAVY)

    c.showPage()
    c.save()


# ---------------------------------------------------------------- back
def draw_qr(c, x, y, size):
    qr = segno.make(QR_URL, error="h", micro=False)
    mat = list(qr.matrix)
    n = len(mat)
    m = size / n
    c.setFillColor(BLACK)
    p = c.beginPath()
    for r, row in enumerate(mat):
        col = 0
        while col < n:  # merge horizontal runs to avoid hairline seams
            if row[col]:
                start = col
                while col < n and row[col]:
                    col += 1
                p.rect(x + start * m, y + size - (r + 1) * m, (col - start) * m, m)
            else:
                col += 1
    c.drawPath(p, stroke=0, fill=1)
    return qr


def build_back(path):
    c = new_page(path)
    fill_rect(c, 0, 0, PAGE_W, PAGE_H, BLUE)

    # dot pattern: strongest at top and bottom edges, fades towards middle
    step = 19
    for gy in range(-11, 450, step):
        for gx in range(-12, 760, step):
            t = max(0.0, 1 - (gy + 11) / 150) * 0.8 + max(0.0, (gy - 270) / 140) * 0.9
            if t < 0.08:
                continue
            c.setFillColor(mix(BLUE, BLUE_DOT, min(t, 1)))
            c.circle(X(gx), Y(gy), 1.7 * S, stroke=0, fill=1)

    # right edge stripe (into bleed)
    fill_rect(c, X(712), 0, PAGE_W - X(712), PAGE_H, BLUE_STRIPE)

    # QR panel
    bx0, by0, bsz = 424, 76, 272
    fill_rect(c, X(bx0), Y(by0 + bsz), bsz * S, bsz * S, WHITE, r=14 * S)
    qpad = 18
    draw_qr(c, X(bx0 + qpad), Y(by0 + bsz - qpad), (bsz - 2 * qpad) * S)

    # copy (left column, shifted right to sit inside the 5 mm safe area)
    tx = 46
    max_w = (bx0 - 12 - tx) * S
    BOLD.draw(c, "Leadzo –", 19.0, X(tx), Y(168), WHITE)
    tag = min(10.5, MEDIUM.fit("for service professionals.", max_w))
    MEDIUM.draw(c, "a lead marketplace", tag, X(tx), Y(214), WHITE)
    MEDIUM.draw(c, "for service professionals.", tag, X(tx), Y(249), WHITE)

    # divider: white fading into the blue
    seg = 40
    for i in range(seg):
        fill_rect(c, X(tx) + i * 102 * S / seg, Y(282), 102 * S / seg + 0.05, 3 * S,
                  mix(WHITE, BLUE, (i / seg) ** 1.6))

    # NEW: call to action under the content
    cta = "Scan to join as a professional"
    arrow_w = 4 + 9
    cta_size = min(9.0, SEMIBOLD.fit(cta, max_w - arrow_w))
    assert cta_size >= 8.0, cta_size
    w = SEMIBOLD.draw(c, cta, cta_size, X(tx), Y(322), WHITE)
    ax, ay = X(tx) + w + 4, Y(322) + cta_size * 0.34   # arrow pointing to the QR
    c.setStrokeColor(WHITE)
    c.setLineWidth(1.1)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.line(ax, ay, ax + 9, ay)
    p = c.beginPath()
    p.moveTo(ax + 6, ay + 3)
    p.lineTo(ax + 9, ay)
    p.lineTo(ax + 6, ay - 3)
    c.drawPath(p, stroke=1, fill=0)

    c.showPage()
    c.save()


def strip_unused_fonts(path):
    """reportlab always registers Helvetica; drop it so the PDF has zero fonts."""
    import pymupdf
    doc = pymupdf.open(path)
    for page in doc:
        page.clean_contents()
        assert b" Tf" not in page.read_contents()
        kind, val = doc.xref_get_key(page.xref, "Resources")
        res = int(val.split()[0]) if kind == "xref" else page.xref
        key = "Font" if kind == "xref" else "Resources/Font"
        doc.xref_set_key(res, key, "null")
    doc.save(path + ".tmp", garbage=4, deflate=True)
    doc.close()
    os.replace(path + ".tmp", path)


def export_qr():
    qr = segno.make(QR_URL, error="h", micro=False)
    qr.save(os.path.join(OUT, "leadzo-join-professional-qr.svg"), scale=10, border=4, dark="#000000")
    qr.save(os.path.join(OUT, "leadzo-join-professional-qr.pdf"), scale=10, border=4)
    qr.save(os.path.join(OUT, "leadzo-join-professional-qr.png"), scale=40, border=4)


if __name__ == "__main__":
    for mode, folder in (("cmyk", "output"), ("rgb", "output-rgb")):
        set_mode(mode)
        OUT = os.path.join(HERE, folder)
        os.makedirs(OUT, exist_ok=True)
        for build, side in ((build_front, "FRONT"), (build_back, "BACK")):
            pdf = os.path.join(OUT, f"leadzo-card-rakshit-{side}.pdf")
            build(pdf)
            strip_unused_fonts(pdf)
        export_qr()
    print("done")
