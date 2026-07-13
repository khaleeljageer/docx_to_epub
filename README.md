# epub_maker

Turn a single Word (`.docx`) file containing many articles into an EPUB e-book,
with a table of contents generated automatically.

## How to format the Word document

For each article, use Word's built-in **paragraph styles** (the style gallery on
the Home tab):

| Part                     | Word style to apply            |
|--------------------------|--------------------------------|
| Article title            | **Title** (this is what starts a new article) |
| Author / translator line | **Subtitle** (optional — leave it out if none) |
| Subheading inside article| **Heading 1** / **Heading 2** / **Heading 3** |
| Article body & tables    | Normal text (no special style) |

Repeat for as many articles as you like in the one file. Only the **Title** style
starts a new article and a new entry in the table of contents. **Heading 1/2/3**
inside an article become subheadings (Heading 1 = biggest), shown in bold larger
text and nested under the article in the table of contents. Tables are kept.

## One-time setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Making an EPUB — the desktop app (recommended)

A native window (built with Qt/PySide6). Run it from source:

```bash
source .venv/bin/activate
python desktop_app.py
```

Then: drag a `.docx` onto the window (or click to choose), check the list of
articles it found (titles, authors, subheadings), fill in the book title /
author / language, and click **Create EPUB…** to save the file.

### Handing it to someone with no Python (standalone build)

```bash
source .venv/bin/activate
pip install pyinstaller
python build_desktop.py
```

This produces a self-contained folder at **`dist/EpubMaker/`**. Zip that folder
and send it to anyone on the **same operating system** — they run the
`EpubMaker` program inside; nothing else to install. (PyInstaller builds per
platform: build on Windows for a Windows build, macOS for macOS, Linux for Linux.)

### Building both Windows and Linux automatically (GitHub Actions)

`.github/workflows/build.yml` builds the app for **Windows and Linux** on every
push (each on its own runner, since PyInstaller can't cross-compile). To use it:

1. Push this project to a GitHub repo.
2. Open the repo's **Actions** tab; the build runs automatically (or click
   *Run workflow* to start it by hand).
3. Download the **`EpubMaker-Windows`** and **`EpubMaker-Linux`** artifacts.

To cut a public release, push a version tag — the workflow then also attaches
both zipped builds to a GitHub Release:

```bash
git tag v1.0
git push origin v1.0
```

> Linux note: the Linux build needs a graphical desktop to run (it bundles Qt,
> but relies on the user's system X11/Wayland libraries — standard on any Linux
> desktop). For a maximally portable Linux binary, an AppImage is a later option.

## Making an EPUB — the web page (optional)

An alternative browser-based UI, if you prefer it over the desktop window:

```bash
source .venv/bin/activate
python app.py
```

Then open **http://127.0.0.1:5000** and follow the same drop → review → download flow.

## Making an EPUB — the command line

```bash
source .venv/bin/activate
python docx_to_epub.py "My Articles.docx" --title "My Book" --author "The Author"
```

This writes `My Articles.epub` next to the input file and prints the list of
articles it found. Options:

- `-o OUTPUT.epub` — choose the output path
- `--title "..."`  — book title (defaults to the file name)
- `--author "..."` — book author / publisher
- `--lang ta`      — language code (e.g. `en`, `ta`, `hi`)

## Notes

- If it says *"no articles found"*, the titles aren't styled **Title**.
- Inline **bold**, *italic*, and underline are preserved.
- All three front-ends (desktop, web, CLI) share the same conversion logic in
  `docx_to_epub.py` (`parse_articles()` / `build_epub()`).
