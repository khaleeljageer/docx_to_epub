"""Cover image generator for the Marxist Tamil monthly e-book magazine.

Produces a simple, consistent "bordered / minimal" cover carrying the Tamil
month name and the year. Output is WebP (small, mobile-friendly).

Public API:
    make_cover(month, year) -> bytes        # WebP image bytes
    slug_for(month, year) -> str            # e.g. "august_2026"
    tamil_title(month, year) -> str         # e.g. "ஆகஸ்ட் 2026"
    date_label(month, year) -> str          # e.g. "Aug, 2026"
"""

from __future__ import annotations

import io
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# --- localisation ---------------------------------------------------------

# Tamil month names, matching the spelling already used in booksdb.json
# (e.g. "ஜூலை 2026").
TAMIL_MONTHS = [
    "ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்",
    "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்",
]

# Lower-case English month names used for the file-name slug, matching the
# existing convention (books/july_2026.epub).
ENGLISH_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

# Short month labels for the booksdb "date" field (e.g. "Jul, 2026").
SHORT_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Magazine name shown at the top of every cover.
MAGAZINE_NAME = "மார்க்சிஸ்ட்"

# --- design constants -----------------------------------------------------

WIDTH, HEIGHT = 1200, 1680          # 5:7 book ratio, matches existing covers

BG_COLOR = (244, 240, 232)          # warm cream
INK_COLOR = (28, 28, 30)            # near-black text
ACCENT_COLOR = (176, 32, 32)        # deep red accent

BORDER_MARGIN = 70                  # outer frame inset from the edges
BORDER_WIDTH = 4


def _check_month_year(month: int, year: int) -> None:
    if not 1 <= int(month) <= 12:
        raise ValueError(f"month must be 1..12, got {month!r}")
    if int(year) < 1:
        raise ValueError(f"year must be positive, got {year!r}")


# --- font loading ---------------------------------------------------------

def _assets_dir() -> str:
    """Directory holding bundled fonts, working both from source and from a
    PyInstaller one-file bundle (which unpacks data under sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "fonts")


def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled Tamil font with libraqm shaping so combined glyphs
    render correctly."""
    path = os.path.join(_assets_dir(), filename)
    try:
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except OSError as exc:
        raise RuntimeError(
            f"Could not load bundled font {path!r}. "
            "Ensure assets/fonts/ ships with the app."
        ) from exc


def _fit_font(filename: str, text: str, max_width: int,
              start_size: int, min_size: int = 24) -> ImageFont.FreeTypeFont:
    """Return the largest font (<= start_size) whose rendered `text` fits in
    `max_width`. Shrinks for long Tamil month names like 'செப்டம்பர்'."""
    size = start_size
    while size > min_size:
        font = _load_font(filename, size)
        if _text_width(font, text) <= max_width:
            return font
        size -= 4
    return _load_font(filename, min_size)


# --- drawing helpers ------------------------------------------------------

def _text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    left, _, right, _ = font.getbbox(text)
    return right - left


def _draw_centered(draw: ImageDraw.ImageDraw, cy: int, text: str,
                   font: ImageFont.FreeTypeFont, fill) -> int:
    """Draw `text` horizontally centered, vertically centered on `cy`.
    Returns the text height."""
    left, top, right, bottom = font.getbbox(text)
    w, h = right - left, bottom - top
    x = (WIDTH - w) // 2 - left
    y = cy - h // 2 - top
    draw.text((x, y), text, font=font, fill=fill)
    return h


# --- public API -----------------------------------------------------------

def slug_for(month: int, year: int) -> str:
    _check_month_year(month, year)
    return f"{ENGLISH_MONTHS[int(month) - 1]}_{int(year)}"


def tamil_title(month: int, year: int) -> str:
    _check_month_year(month, year)
    return f"{TAMIL_MONTHS[int(month) - 1]} {int(year)}"


def date_label(month: int, year: int) -> str:
    _check_month_year(month, year)
    return f"{SHORT_MONTHS[int(month) - 1]}, {int(year)}"


def make_cover(month: int, year: int, quality: int = 82) -> bytes:
    """Render the cover for the given month/year and return WebP bytes."""
    _check_month_year(month, year)
    month, year = int(month), int(year)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Inset border frame.
    draw.rectangle(
        [BORDER_MARGIN, BORDER_MARGIN, WIDTH - BORDER_MARGIN, HEIGHT - BORDER_MARGIN],
        outline=INK_COLOR, width=BORDER_WIDTH,
    )

    inner_width = WIDTH - 2 * (BORDER_MARGIN + 60)

    # Magazine name near the top, in accent red.
    name_font = _fit_font("NotoSerifTamil-Bold.ttf", MAGAZINE_NAME,
                          inner_width, start_size=78)
    _draw_centered(draw, BORDER_MARGIN + 140, MAGAZINE_NAME, name_font, ACCENT_COLOR)

    # Thin rule under the magazine name.
    rule_y = BORDER_MARGIN + 210
    rule_half = inner_width // 4
    draw.line([(WIDTH // 2 - rule_half, rule_y), (WIDTH // 2 + rule_half, rule_y)],
              fill=INK_COLOR, width=2)

    # Tamil month name, large, centered in the page.
    month_text = TAMIL_MONTHS[month - 1]
    month_font = _fit_font("NotoSerifTamil-Bold.ttf", month_text,
                           inner_width, start_size=180)
    _draw_centered(draw, HEIGHT // 2 - 40, month_text, month_font, INK_COLOR)

    # Year below the month.
    year_font = _load_font("NotoSerifTamil-Regular.ttf", 120)
    _draw_centered(draw, HEIGHT // 2 + 150, str(year), year_font, INK_COLOR)

    # Short accent rule under the year.
    accent_y = HEIGHT // 2 + 260
    accent_half = 110
    draw.line([(WIDTH // 2 - accent_half, accent_y), (WIDTH // 2 + accent_half, accent_y)],
              fill=ACCENT_COLOR, width=6)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate a magazine cover (WebP).")
    parser.add_argument("month", type=int, help="month number 1-12")
    parser.add_argument("year", type=int, help="year e.g. 2026")
    parser.add_argument("-o", "--out", help="output path (default: <slug>.webp)")
    args = parser.parse_args()

    data = make_cover(args.month, args.year)
    out = args.out or f"{slug_for(args.month, args.year)}.webp"
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"Wrote {out} ({len(data):,} bytes) — {tamil_title(args.month, args.year)}")
