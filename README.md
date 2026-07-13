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

### Publishing a monthly issue to the books website

After you create an EPUB, the **Publish to GitHub…** button uploads it to the
[MarxistTamilEbooks](https://github.com/tamilmarxist/MarxistTamilEbooks) repo so
it appears in the mobile app. One click does three things:

1. uploads the EPUB to `books/<month>_<year>.epub`;
2. **generates a cover** (a simple bordered design with the Tamil month + year)
   and uploads it to `images/<month>_<year>.webp` — WebP keeps it small for
   mobile;
3. adds (or updates) the book's entry in `booksdb.json`, newest first.

In the dialog, paste a **GitHub token**, pick the **month** and **year** (these
are pre-filled from the file name), and click **Publish**. Re-publishing the same
month overwrites its files and updates the existing entry instead of creating a
duplicate.

**Getting a token:** on GitHub go to *Settings → Developer settings →
Fine-grained personal access tokens → Generate new token*. Limit it to the
**MarxistTamilEbooks** repository and give it **Repository permissions →
Contents: Read and write**. Paste the generated token into the dialog; tick
*Remember token on this computer* to save it for next time (stored locally in
your OS settings — treat it like a password and don't share the build with the
token baked in).

You can also publish from the command line without the GUI:

```bash
GITHUB_TOKEN=your_token python publisher.py path/to/book.epub 7 2026
```

### Handing it to someone with no Python (standalone build)

```bash
source .venv/bin/activate
pip install pyinstaller
python build_desktop.py
```

This produces a **single self-contained executable**:

- Windows → `dist\EpubMaker.exe`
- Linux → `dist/EpubMaker`
- macOS → `dist/EpubMaker`

Send that **one file** to anyone on the **same operating system** — they just run
it; nothing else to install, and there's no separate dependency folder that could
be moved or deleted. (PyInstaller builds per platform: build on Windows for a
Windows build, macOS for macOS, Linux for Linux.) A onefile app unpacks itself on
launch, so the **first start takes a few seconds** — that's normal.

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
