#!/usr/bin/env python3
"""
docx_to_epub.py — Turn a single .docx of multiple articles into an EPUB book.

Source document convention
--------------------------
Each article is laid out as:

    <Article title>      -> paragraph styled "Heading 1"
    <Author / translator> -> the next paragraph, styled "Subtitle" / "Heading 2"
                             / "Author" (optional; omit it and it's just skipped)
    <Article body...>    -> everything else until the next "Heading 1"

One .docx may hold any number of articles. A table of contents is generated
automatically, one entry per article. Tables in the body are preserved.

Usage
-----
    python docx_to_epub.py INPUT.docx [-o OUTPUT.epub] [--title "Book title"]
                           [--author "Book author"] [--lang ta]

If -o is omitted, the epub is written next to the input with the same stem.
The functions parse_articles() and build_epub() are import-friendly so a UI
can reuse them.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.document import Document as _Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from ebooklib import epub

# --- Style-name matching (case-insensitive, forgiving of Word variants) ----
# Word localises and renames styles, so we match loosely.
#   Article title  -> "Title"  (the ONLY style that starts a new article)
#   Author line    -> "Subtitle" (the paragraph right after the title)
#   Subheadings    -> "Heading 1" / "Heading 2" / "Heading 3" ... in the body
TITLE_STYLES = {"title"}
AUTHOR_STYLES = {"subtitle", "author", "byline"}


def _norm(style_name: str | None) -> str:
    return (style_name or "").strip().lower()


def _is_title(p: Paragraph) -> bool:
    return _norm(p.style.name if p.style else None) in TITLE_STYLES


def _is_author(p: Paragraph) -> bool:
    return _norm(p.style.name if p.style else None) in AUTHOR_STYLES


def _heading_level(p: Paragraph) -> int | None:
    """Return N for an in-content 'Heading N' subheading, else None.

    Only "Title" marks an article boundary, so every 'Heading N' (N >= 1) is a
    subheading inside the body.
    """
    m = re.match(r"heading\s*(\d+)", _norm(p.style.name if p.style else None))
    if m:
        return int(m.group(1))
    return None


# --- Ordered iteration over a docx body (paragraphs AND tables in order) ----
def _iter_block_items(parent):
    """Yield Paragraph and Table objects in document order."""
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise TypeError(f"unsupported parent: {type(parent)!r}")

    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


# --- Inline / block HTML rendering -----------------------------------------
def _run_to_html(run) -> str:
    text = html.escape(run.text or "")
    if not text:
        # Preserve intentional line breaks inside a run's XML.
        if run._element.findall(qn("w:br")):
            return "<br/>"
        return ""
    if run.bold:
        text = f"<strong>{text}</strong>"
    if run.italic:
        text = f"<em>{text}</em>"
    if run.underline:
        text = f"<u>{text}</u>"
    return text


def _paragraph_to_html(p: Paragraph) -> str:
    inner = "".join(_run_to_html(r) for r in p.runs).strip()
    if not inner:
        return ""
    align = (p.alignment and str(p.alignment).split()[0].lower()) or ""
    style = ' style="text-align:center"' if "center" in align else (
        ' style="text-align:right"' if "right" in align else "")
    return f"<p{style}>{inner}</p>"


def _cell_to_html(cell: _Cell) -> str:
    parts = []
    for block in _iter_block_items(cell):
        if isinstance(block, Paragraph):
            inner = "".join(_run_to_html(r) for r in block.runs).strip()
            if inner:
                parts.append(inner)
        elif isinstance(block, Table):
            parts.append(_table_to_html(block))
    return "<br/>".join(parts) if parts else "&#160;"


def _table_to_html(table: Table) -> str:
    rows_html = []
    for i, row in enumerate(table.rows):
        tag = "th" if i == 0 else "td"
        cells = "".join(f"<{tag}>{_cell_to_html(c)}</{tag}>" for c in row.cells)
        rows_html.append(f"<tr>{cells}</tr>")
    return '<table class="content-table">' + "".join(rows_html) + "</table>"


# --- Data model -------------------------------------------------------------
@dataclass
class Subheading:
    anchor: str  # id used for the in-book TOC link
    text: str
    level: int


@dataclass
class Article:
    title: str
    author: str = ""
    body_html: list[str] = field(default_factory=list)
    subheadings: list[Subheading] = field(default_factory=list)

    def to_html(self) -> str:
        parts = [f"<h1>{html.escape(self.title)}</h1>"]
        if self.author:
            parts.append(f'<p class="author">{html.escape(self.author)}</p>')
        parts.extend(self.body_html)
        return "\n".join(parts)


# --- Parsing ----------------------------------------------------------------
def parse_articles(docx_path: str | Path) -> list[Article]:
    """Split a .docx into a list of Article objects using the style convention."""
    document = docx.Document(str(docx_path))
    articles: list[Article] = []
    current: Article | None = None
    expecting_author = False  # true right after a title, until first body block

    for block in _iter_block_items(document):
        if isinstance(block, Paragraph) and _is_title(block):
            title_text = block.text.strip()
            if not title_text:
                continue  # ignore empty heading paragraphs
            current = Article(title=title_text)
            articles.append(current)
            expecting_author = True
            continue

        if current is None:
            # Content before the first title (front matter) is ignored.
            continue

        if isinstance(block, Paragraph):
            if expecting_author and _is_author(block) and block.text.strip():
                current.author = block.text.strip()
                expecting_author = False
                continue
            expecting_author = False

            level = _heading_level(block)
            if level is not None and block.text.strip():
                anchor = f"sec{len(current.subheadings) + 1}"
                current.subheadings.append(
                    Subheading(anchor=anchor, text=block.text.strip(), level=level)
                )
                inner = "".join(_run_to_html(r) for r in block.runs).strip()
                # Article title is <h1>; offset subheadings by one so Word
                # "Heading 1"->h2, "Heading 2"->h3, ... capped at h4.
                tag = f"h{min(level + 1, 4)}"
                current.body_html.append(
                    f'<{tag} id="{anchor}" class="subhead">{inner}</{tag}>'
                )
                continue

            frag = _paragraph_to_html(block)
            if frag:
                current.body_html.append(frag)
        elif isinstance(block, Table):
            expecting_author = False
            current.body_html.append(_table_to_html(block))

    return articles


# --- EPUB building ----------------------------------------------------------
CSS = """
body { font-family: serif; line-height: 1.6; margin: 5%; }
h1 { font-size: 1.5em; margin-bottom: 0.2em; }
h2.subhead { font-size: 1.25em; margin: 1.4em 0 0.4em; }
h3.subhead { font-size: 1.1em; margin: 1.2em 0 0.3em; }
h4.subhead { font-size: 1em; margin: 1em 0 0.3em; }
p.author { font-style: italic; color: #555; margin-top: 0; margin-bottom: 1.2em; }
p { margin: 0 0 0.8em; text-align: justify; }
table.content-table { border-collapse: collapse; width: 100%; margin: 1em 0; }
table.content-table th, table.content-table td {
    border: 1px solid #888; padding: 0.4em 0.6em; text-align: left; vertical-align: top;
}
table.content-table th { background: #eee; font-weight: bold; }
"""


def build_epub(
    articles: list[Article],
    out_path: str | Path,
    *,
    title: str = "Untitled",
    author: str = "Unknown",
    language: str = "en",
) -> Path:
    """Write the articles to an EPUB file with an auto-generated TOC."""
    if not articles:
        raise ValueError("No articles found. Check that titles use the 'Heading 1' style.")

    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    css_item = epub.EpubItem(
        uid="style", file_name="style/main.css",
        media_type="text/css", content=CSS,
    )
    book.add_item(css_item)

    chapters = []
    toc_entries = []
    for i, art in enumerate(articles, start=1):
        fname = f"article_{i:03d}.xhtml"
        ch = epub.EpubHtml(title=art.title, file_name=fname, lang=language)
        ch.content = f"<html><body>{art.to_html()}</body></html>"
        ch.add_item(css_item)
        book.add_item(ch)
        chapters.append(ch)

        # TOC: one entry per article, with subheadings nested beneath it.
        art_link = epub.Link(fname, art.title, f"art{i}")
        if art.subheadings:
            children = tuple(
                epub.Link(f"{fname}#{s.anchor}", s.text, f"art{i}_{s.anchor}")
                for s in art.subheadings
            )
            toc_entries.append((art_link, children))
        else:
            toc_entries.append(art_link)

    book.toc = tuple(toc_entries)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]

    out_path = Path(out_path)
    epub.write_epub(str(out_path), book)
    return out_path


# --- CLI --------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert a multi-article .docx into an EPUB.")
    ap.add_argument("input", help="Path to the source .docx file")
    ap.add_argument("-o", "--output", help="Output .epub path (default: alongside input)")
    ap.add_argument("--title", help="Book title (default: input file name)")
    ap.add_argument("--author", default="Unknown", help="Book author/publisher")
    ap.add_argument("--lang", default="en", help="Language code, e.g. en, ta, hi")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"error: file not found: {in_path}", file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else in_path.with_suffix(".epub")
    book_title = args.title or in_path.stem

    try:
        articles = parse_articles(in_path)
        if not articles:
            print("error: no articles found — are titles styled 'Heading 1'?", file=sys.stderr)
            return 2
        build_epub(articles, out_path, title=book_title, author=args.author, language=args.lang)
    except Exception as exc:  # noqa: BLE001 — surface a friendly message to end users
        print(f"error: {exc}", file=sys.stderr)
        return 3

    print(f"OK  {len(articles)} article(s) -> {out_path}")
    for i, a in enumerate(articles, 1):
        who = f" — {a.author}" if a.author else ""
        print(f"  {i:>3}. {a.title}{who}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
