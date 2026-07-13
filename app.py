#!/usr/bin/env python3
"""
app.py — Simple web UI for the docx-to-epub maker.

Run it:
    source .venv/bin/activate
    python app.py

Then open http://127.0.0.1:5000 in a browser. Drop a .docx, check the list of
articles it found, fill in the book title/author, and download the EPUB.

This is a thin UI over docx_to_epub.parse_articles() / build_epub(); all the
conversion logic lives there.
"""
from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort
from werkzeug.utils import secure_filename

from docx_to_epub import parse_articles, build_epub

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

# Uploaded .docx files are parked here, keyed by a random token, so the browser
# can preview the article list and then ask for the EPUB without re-uploading.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "epub_maker_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_AGE_SECONDS = 60 * 60  # discard stashed uploads older than an hour


def _sweep_old_uploads() -> None:
    cutoff = time.time() - MAX_AGE_SECONDS
    for f in UPLOAD_DIR.glob("*.docx"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _stash_path(token: str) -> Path:
    # token is a uuid we generate, so it is safe as a filename.
    return UPLOAD_DIR / f"{token}.docx"


@app.get("/")
def index():
    return PAGE


@app.post("/upload")
def upload():
    """Receive a .docx, parse it, and return the detected articles as JSON."""
    _sweep_old_uploads()
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(error="No file was selected."), 400
    if not file.filename.lower().endswith(".docx"):
        return jsonify(error="Please choose a Word .docx file."), 400

    token = uuid.uuid4().hex
    dest = _stash_path(token)
    file.save(dest)

    try:
        articles = parse_articles(dest)
    except Exception as exc:  # noqa: BLE001 — report parse failures to the user
        dest.unlink(missing_ok=True)
        return jsonify(error=f"Could not read the document: {exc}"), 400

    if not articles:
        dest.unlink(missing_ok=True)
        return jsonify(
            error="No articles found. Make sure each article title uses the "
                  "'Title' style in Word."
        ), 400

    return jsonify(
        token=token,
        original_name=secure_filename(file.filename),
        articles=[
            {
                "title": a.title,
                "author": a.author,
                "subheadings": [s.text for s in a.subheadings],
            }
            for a in articles
        ],
    )


@app.post("/convert")
def convert():
    """Build and return the EPUB for a previously uploaded document."""
    token = (request.form.get("token") or "").strip()
    if not token or not token.isalnum():
        abort(400, "Missing or invalid upload token.")
    src = _stash_path(token)
    if not src.is_file():
        abort(404, "Upload expired — please add the file again.")

    title = (request.form.get("title") or "Untitled").strip() or "Untitled"
    author = (request.form.get("author") or "Unknown").strip() or "Unknown"
    lang = (request.form.get("lang") or "en").strip() or "en"

    try:
        articles = parse_articles(src)
        out_path = UPLOAD_DIR / f"{token}.epub"
        build_epub(articles, out_path, title=title, author=author, language=lang)
    except Exception as exc:  # noqa: BLE001
        abort(400, f"Could not build the EPUB: {exc}")

    safe = secure_filename(title) or "book"
    return send_file(
        out_path,
        as_attachment=True,
        download_name=f"{safe}.epub",
        mimetype="application/epub+zip",
    )


# --- Single-page UI (kept inline so the tool is just app.py + docx_to_epub.py) ---
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DOCX to EPUB maker</title>
<style>
  :root { --accent:#2b6cb0; --border:#d0d5dd; --bg:#f7f8fa; --ok:#2f855a; --err:#c53030; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 0; background: var(--bg); color: #1a202c; line-height: 1.5; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 2rem 1.2rem 4rem; }
  h1 { font-size: 1.5rem; margin: 0 0 .3rem; }
  p.sub { margin: 0 0 1.6rem; color: #5a6473; }
  .card { background: #fff; border: 1px solid var(--border); border-radius: 12px;
          padding: 1.4rem; margin-bottom: 1.2rem; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
  #drop { border: 2px dashed var(--border); border-radius: 12px; padding: 2.2rem 1rem;
          text-align: center; cursor: pointer; transition: .15s; background: #fbfcfe; }
  #drop.hover { border-color: var(--accent); background: #eef4fb; }
  #drop strong { color: var(--accent); }
  .muted { color: #7a8494; font-size: .9rem; }
  label { display: block; font-weight: 600; margin: .9rem 0 .3rem; font-size: .92rem; }
  input[type=text] { width: 100%; padding: .6rem .7rem; border: 1px solid var(--border);
                     border-radius: 8px; font-size: 1rem; }
  .row { display: flex; gap: 1rem; flex-wrap: wrap; }
  .row > div { flex: 1 1 200px; }
  button { font: inherit; font-weight: 600; border: 0; border-radius: 8px; padding: .7rem 1.2rem;
           cursor: pointer; }
  .primary { background: var(--accent); color: #fff; }
  .primary:disabled { background: #9db8d6; cursor: not-allowed; }
  .msg { padding: .7rem .9rem; border-radius: 8px; margin-top: 1rem; display: none; }
  .msg.err { background: #fff5f5; color: var(--err); border: 1px solid #feb2b2; display: block; }
  .msg.ok  { background: #f0fff4; color: var(--ok);  border: 1px solid #9ae6b4; display: block; }
  ol.articles { margin: .4rem 0 0; padding-left: 1.4rem; }
  ol.articles li { margin: .5rem 0; }
  ol.articles .author { color: #5a6473; font-style: italic; }
  ol.articles .subs { color: #7a8494; font-size: .86rem; margin: .15rem 0 0; }
  .hidden { display: none; }
  .fileline { margin-top: .8rem; font-size: .92rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>DOCX &rarr; EPUB maker</h1>
  <p class="sub">Turn one Word file of many articles into an e-book with a table of contents.</p>

  <div class="card">
    <div id="drop">
      <p><strong>Click to choose</strong> or drag a <code>.docx</code> file here</p>
      <p class="muted">Titles use the <b>Title</b> style; author uses <b>Subtitle</b>;
         subheadings use <b>Heading 1/2/3</b>.</p>
      <input id="file" type="file" accept=".docx" class="hidden">
    </div>
    <div id="fileline" class="fileline muted"></div>
    <div id="uploadMsg" class="msg"></div>
  </div>

  <div id="step2" class="card hidden">
    <p><b id="count"></b> found. Check the list, then fill in the book details.</p>
    <ol id="articles" class="articles"></ol>

    <div class="row">
      <div>
        <label for="title">Book title</label>
        <input id="title" type="text" placeholder="e.g. Theekkathir July 2026">
      </div>
      <div>
        <label for="author">Author / publisher</label>
        <input id="author" type="text" placeholder="e.g. Theekkathir">
      </div>
      <div style="flex:0 0 120px">
        <label for="lang">Language</label>
        <input id="lang" type="text" value="ta">
      </div>
    </div>

    <p style="margin-top:1.2rem">
      <button id="download" class="primary">Download EPUB</button>
    </p>
    <div id="convertMsg" class="msg"></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const drop = $('#drop'), fileInput = $('#file');
let token = null;

drop.addEventListener('click', () => fileInput.click());
['dragover','dragenter'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add('hover');
}));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove('hover');
}));
drop.addEventListener('drop', ev => {
  if (ev.dataTransfer.files.length) { fileInput.files = ev.dataTransfer.files; handleUpload(); }
});
fileInput.addEventListener('change', handleUpload);

function show(el, kind, text) { el.className = 'msg ' + kind; el.textContent = text; }
function esc(s){ return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function handleUpload() {
  const f = fileInput.files[0];
  if (!f) return;
  $('#fileline').textContent = 'Selected: ' + f.name;
  $('#uploadMsg').className = 'msg';
  $('#step2').classList.add('hidden');
  const fd = new FormData();
  fd.append('file', f);
  try {
    const r = await fetch('/upload', { method: 'POST', body: fd });
    const data = await r.json();
    if (!r.ok) { show($('#uploadMsg'), 'err', data.error || 'Upload failed.'); return; }
    token = data.token;
    renderArticles(data.articles);
    if (!$('#title').value) $('#title').value = f.name.replace(/\.docx$/i, '');
    $('#step2').classList.remove('hidden');
    $('#step2').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    show($('#uploadMsg'), 'err', 'Could not reach the server.');
  }
}

function renderArticles(articles) {
  $('#count').textContent = articles.length + (articles.length === 1 ? ' article' : ' articles');
  const ol = $('#articles'); ol.innerHTML = '';
  for (const a of articles) {
    const li = document.createElement('li');
    let h = '<span class="title">' + esc(a.title) + '</span>';
    if (a.author) h += ' <span class="author">— ' + esc(a.author) + '</span>';
    if (a.subheadings && a.subheadings.length)
      h += '<div class="subs">' + a.subheadings.length + ' subheading' +
           (a.subheadings.length === 1 ? '' : 's') + ': ' +
           a.subheadings.map(esc).join(' · ') + '</div>';
    li.innerHTML = h;
    ol.appendChild(li);
  }
}

$('#download').addEventListener('click', async () => {
  if (!token) return;
  const btn = $('#download'); btn.disabled = true; btn.textContent = 'Building…';
  $('#convertMsg').className = 'msg';
  const fd = new FormData();
  fd.append('token', token);
  fd.append('title', $('#title').value.trim() || 'Untitled');
  fd.append('author', $('#author').value.trim() || 'Unknown');
  fd.append('lang', $('#lang').value.trim() || 'en');
  try {
    const r = await fetch('/convert', { method: 'POST', body: fd });
    if (!r.ok) {
      let m = 'Conversion failed.';
      try { m = (await r.text()) || m; } catch (e) {}
      show($('#convertMsg'), 'err', m); return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = ($('#title').value.trim() || 'book').replace(/[^\w.-]+/g, '_') + '.epub';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    show($('#convertMsg'), 'ok', 'EPUB downloaded. Check your Downloads folder.');
  } catch (e) {
    show($('#convertMsg'), 'err', 'Could not reach the server.');
  } finally {
    btn.disabled = false; btn.textContent = 'Download EPUB';
  }
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("EPUB maker UI running at  http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
