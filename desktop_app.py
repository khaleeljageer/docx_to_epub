#!/usr/bin/env python3
"""
desktop_app.py — Native desktop UI (PySide6/Qt) for the docx-to-epub maker.

Run from source:
    source .venv/bin/activate
    python desktop_app.py

Or build a standalone executable anyone can run (see build_desktop.py / README).

The window: pick or drag a .docx, review the articles it found, fill in the
book title/author/language, and save the EPUB. All conversion is done by
docx_to_epub.parse_articles() / build_epub().
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSettings
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QDialog, QComboBox, QSpinBox,
    QPlainTextEdit, QCheckBox,
)

import cover
from docx_to_epub import parse_articles, build_epub, Article
from publisher import GitHubPublisher

APP_NAME = "DOCX to EPUB maker"

SETTINGS_ORG = "MarxistTamil"
SETTINGS_APP = "EpubMaker"


# --- Background worker so building a big book never freezes the window -------
class BuildWorker(QObject):
    done = Signal(str)     # emits output path on success
    failed = Signal(str)   # emits error message

    def __init__(self, articles, out_path, title, author, lang):
        super().__init__()
        self._args = (articles, out_path, title, author, lang)

    def run(self):
        articles, out_path, title, author, lang = self._args
        try:
            build_epub(articles, out_path, title=title, author=author, language=lang)
            self.done.emit(str(out_path))
        except Exception as exc:  # noqa: BLE001 — surfaced in a dialog
            self.failed.emit(str(exc))


class PublishWorker(QObject):
    """Uploads a built EPUB (+ generated cover) to the GitHub books repo."""
    progress = Signal(str)   # log lines from the publisher
    done = Signal(dict)      # result dict from GitHubPublisher.publish
    failed = Signal(str)     # error message

    def __init__(self, epub_path, month, year, token):
        super().__init__()
        self._args = (epub_path, month, year, token)

    def run(self):
        epub_path, month, year, token = self._args
        try:
            with open(epub_path, "rb") as fh:
                data = fh.read()
            pub = GitHubPublisher(token, log=self.progress.emit)
            result = pub.publish(data, month, year)
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001 — surfaced in the dialog log
            self.failed.emit(str(exc))


class DropLabel(QLabel):
    """A click/drag target for choosing a .docx file."""
    fileChosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setText(
            "Drag a .docx file here\n\nor click to choose one"
        )
        self.setObjectName("drop")
        self.setMinimumHeight(130)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose a Word document", "", "Word documents (*.docx)"
            )
            if path:
                self.fileChosen.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".docx"):
                    self.setProperty("hover", True)
                    self._restyle()
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("hover", False)
        self._restyle()

    def dropEvent(self, event):
        self.setProperty("hover", False)
        self._restyle()
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".docx"):
                self.fileChosen.emit(p)
                return

    def _restyle(self):
        # Force Qt to re-evaluate the stylesheet after a property change.
        self.style().unpolish(self)
        self.style().polish(self)


def _guess_month_year(name: str) -> tuple[int, int]:
    """Best-effort month/year from a file name like 'july_2026'; falls back to
    today's date."""
    today = date.today()
    lower = name.lower()
    month = next((i + 1 for i, m in enumerate(cover.ENGLISH_MONTHS) if m in lower),
                 today.month)
    year_match = re.search(r"(19|20|21)\d{2}", name)
    year = int(year_match.group()) if year_match else today.year
    return month, year


class PublishDialog(QDialog):
    """Collects a GitHub token + month/year and streams the upload progress."""

    def __init__(self, parent, epub_path: str, guess_name: str):
        super().__init__(parent)
        self.setWindowTitle("Publish to GitHub")
        self.setMinimumWidth(520)
        self._epub_path = epub_path
        self._thread: QThread | None = None
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        intro = QLabel(
            f"Upload <b>{Path(epub_path).name}</b> to the MarxistTamilEbooks "
            "repository. A cover image is generated automatically and "
            "<code>booksdb.json</code> is updated."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("GitHub token (Contents: read & write)")
        self.token_edit.setText(self._settings.value("github_token", "", str))

        g_month, g_year = _guess_month_year(guess_name)
        self.month_combo = QComboBox()
        for i, (en, ta) in enumerate(zip(cover.ENGLISH_MONTHS, cover.TAMIL_MONTHS), 1):
            self.month_combo.addItem(f"{en.capitalize()} — {ta}", i)
        self.month_combo.setCurrentIndex(g_month - 1)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(g_year)
        self.year_spin.setMaximumWidth(110)

        self.remember_check = QCheckBox("Remember token on this computer")
        self.remember_check.setChecked(bool(self._settings.value("github_token", "", str)))

        form.addRow("GitHub token", self.token_edit)
        form.addRow("Month", self.month_combo)
        form.addRow("Year", self.year_spin)
        form.addRow("", self.remember_check)
        root.addLayout(form)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("log")
        self.log_view.setMinimumHeight(150)
        self.log_view.setPlaceholderText("Progress will appear here…")
        root.addWidget(self.log_view, stretch=1)

        btn_row = QHBoxLayout()
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        self.publish_btn = QPushButton("Publish")
        self.publish_btn.setObjectName("primary")
        self.publish_btn.clicked.connect(self._start)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        btn_row.addWidget(self.publish_btn)
        root.addLayout(btn_row)

    def _append(self, line: str):
        self.log_view.appendPlainText(line)

    def _set_inputs_enabled(self, on: bool):
        for w in (self.token_edit, self.month_combo, self.year_spin,
                  self.remember_check, self.publish_btn):
            w.setEnabled(on)

    def _start(self):
        token = self.token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Token required",
                                "Please paste a GitHub token with Contents write access.")
            return

        if self.remember_check.isChecked():
            self._settings.setValue("github_token", token)
        else:
            self._settings.remove("github_token")

        month = self.month_combo.currentData()
        year = self.year_spin.value()

        self._set_inputs_enabled(False)
        self.close_btn.setEnabled(False)
        self.log_view.clear()

        self._thread = QThread()
        self._worker = PublishWorker(self._epub_path, month, year, token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._append)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, result: dict):
        self.close_btn.setEnabled(True)
        self._append("")
        self._append("✓ Published successfully.")
        self._append(f"   EPUB:  {result['epub_url']}")
        self._append(f"   Cover: {result['image_url']}")
        QMessageBox.information(
            self, "Published",
            f"“{result['title']}” is now live.\n\n"
            f"EPUB and cover uploaded, and booksdb.json updated.",
        )

    def _on_failed(self, msg: str):
        self._set_inputs_enabled(True)
        self.close_btn.setEnabled(True)
        self._append("")
        self._append(f"✗ Failed: {msg}")
        QMessageBox.critical(self, "Publish failed", msg)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(640, 640)

        self._articles: list[Article] = []
        self._docx_path: Path | None = None
        self._epub_path: str | None = None
        self._thread: QThread | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        # Header
        title = QLabel(APP_NAME)
        f = QFont(); f.setPointSize(16); f.setBold(True)
        title.setFont(f)
        root.addWidget(title)
        sub = QLabel("Turn one Word file of many articles into an e-book with a "
                     "table of contents.")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        root.addWidget(sub)

        # Drop area
        self.drop = DropLabel()
        self.drop.fileChosen.connect(self.load_docx)
        root.addWidget(self.drop)

        hint = QLabel("Titles use the “Title” style · author uses “Subtitle” · "
                      "subheadings use “Heading 1/2/3”.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Articles found
        self.found_label = QLabel("")
        self.found_label.setObjectName("found")
        root.addWidget(self.found_label)
        self.articles_list = QListWidget()
        self.articles_list.setSelectionMode(QListWidget.NoSelection)
        self.articles_list.setFocusPolicy(Qt.NoFocus)
        root.addWidget(self.articles_list, stretch=1)

        # Book details form
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setObjectName("rule")
        root.addWidget(line)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.title_edit = QLineEdit(); self.title_edit.setPlaceholderText("e.g. Theekkathir July 2026")
        self.author_edit = QLineEdit(); self.author_edit.setPlaceholderText("e.g. Theekkathir")
        self.lang_edit = QLineEdit("ta"); self.lang_edit.setMaximumWidth(80)
        form.addRow("Book title", self.title_edit)
        form.addRow("Author / publisher", self.author_edit)
        form.addRow("Language code", self.lang_edit)
        root.addLayout(form)

        # Actions
        btn_row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.publish_btn = QPushButton("Publish to GitHub…")
        self.publish_btn.setObjectName("secondary")
        self.publish_btn.setEnabled(False)
        self.publish_btn.clicked.connect(self.publish_epub)
        self.make_btn = QPushButton("Create EPUB…")
        self.make_btn.setObjectName("primary")
        self.make_btn.setEnabled(False)
        self.make_btn.clicked.connect(self.create_epub)
        btn_row.addWidget(self.status)
        btn_row.addWidget(self.publish_btn)
        btn_row.addWidget(self.make_btn)
        root.addLayout(btn_row)

    # --- Loading / parsing --------------------------------------------------
    def load_docx(self, path: str):
        p = Path(path)
        self.drop.setText(f"📄  {p.name}\n\n(click to choose a different file)")
        self.status.setText("Reading…")
        QApplication.processEvents()
        try:
            articles = parse_articles(p)
        except Exception as exc:  # noqa: BLE001
            self._error("Could not read the document", str(exc))
            self.status.setText("")
            return

        if not articles:
            self._error(
                "No articles found",
                "Make sure each article title uses the “Title” style in Word.",
            )
            self.status.setText("")
            return

        self._docx_path = p
        self._articles = articles
        self._show_articles(articles)
        if not self.title_edit.text().strip():
            self.title_edit.setText(p.stem)
        self.make_btn.setEnabled(True)
        self.publish_btn.setEnabled(False)
        self._epub_path = None
        self.status.setText("")

    def _show_articles(self, articles: list[Article]):
        n = len(articles)
        self.found_label.setText(f"{n} article{'s' if n != 1 else ''} found:")
        self.articles_list.clear()
        for i, a in enumerate(articles, 1):
            bits = [f"{i}.  {a.title}"]
            if a.author:
                bits.append(f"      — {a.author}")
            if a.subheadings:
                subs = " · ".join(s.text for s in a.subheadings)
                bits.append(f"      {len(a.subheadings)} subheading"
                            f"{'s' if len(a.subheadings) != 1 else ''}: {subs}")
            item = QListWidgetItem("\n".join(bits))
            self.articles_list.addItem(item)

    # --- Building -----------------------------------------------------------
    def create_epub(self):
        if not self._articles or self._docx_path is None:
            return
        title = self.title_edit.text().strip() or "Untitled"
        default_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip() or "book"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save EPUB as",
            str(self._docx_path.with_name(default_name + ".epub")),
            "EPUB e-book (*.epub)",
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".epub"):
            out_path += ".epub"

        author = self.author_edit.text().strip() or "Unknown"
        lang = self.lang_edit.text().strip() or "en"

        self.make_btn.setEnabled(False)
        self.publish_btn.setEnabled(False)
        self._epub_path = None
        self.status.setText("Building EPUB…")

        # Run the build off the UI thread.
        self._thread = QThread()
        self._worker = BuildWorker(self._articles, out_path, title, author, lang)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_built)
        self._worker.failed.connect(self._on_build_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_built(self, out_path: str):
        self.status.setText("")
        self.make_btn.setEnabled(True)
        self._epub_path = out_path
        self.publish_btn.setEnabled(True)
        QMessageBox.information(
            self, APP_NAME,
            f"Done!\n\nSaved EPUB with {len(self._articles)} article"
            f"{'s' if len(self._articles) != 1 else ''} to:\n{out_path}"
            "\n\nUse “Publish to GitHub…” to upload it to the books repo.",
        )

    # --- Publishing ---------------------------------------------------------
    def publish_epub(self):
        if not self._epub_path or not Path(self._epub_path).exists():
            self._error("Nothing to publish",
                        "Create an EPUB first, then publish it.")
            return
        guess = Path(self._epub_path).stem
        if self._docx_path is not None:
            guess = f"{guess} {self._docx_path.stem}"
        dlg = PublishDialog(self, self._epub_path, guess)
        dlg.exec()

    def _on_build_failed(self, msg: str):
        self.status.setText("")
        self.make_btn.setEnabled(True)
        self._error("Could not build the EPUB", msg)

    def _error(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg)


# Two self-consistent palettes so the app reads cleanly on either OS theme
# instead of inheriting a dark window background under dark text.
LIGHT = {
    "bg": "#f7f8fa", "text": "#1a202c", "muted": "#6b7280",
    "panel": "#ffffff", "border": "#cbd5e0", "border_soft": "#e2e8f0",
    "item_line": "#f0f2f5", "drop_bg": "#fbfcfe", "drop_hover": "#eef4fb",
    "accent": "#2b6cb0", "accent_hover": "#255992", "accent_off": "#9db8d6",
    "on_accent": "#ffffff",
}
DARK = {
    "bg": "#22262c", "text": "#e6e8eb", "muted": "#9aa4b2",
    "panel": "#2a2f36", "border": "#3a4149", "border_soft": "#343a42",
    "item_line": "#343a42", "drop_bg": "#262b31", "drop_hover": "#2f3742",
    "accent": "#3b82c4", "accent_hover": "#4a90d0", "accent_off": "#3a4149",
    "on_accent": "#ffffff",
}


def build_style(c: dict) -> str:
    return f"""
QWidget {{ font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px;
          color: {c['text']}; background: {c['bg']}; }}
QLabel#muted {{ color: {c['muted']}; font-size: 12px; background: transparent; }}
QLabel#found {{ font-weight: 600; margin-top: 4px; background: transparent; }}
QLabel#drop {{
    border: 2px dashed {c['border']}; border-radius: 12px; background: {c['drop_bg']};
    color: {c['accent']}; font-size: 15px;
}}
QLabel#drop[hover="true"] {{ border-color: {c['accent']}; background: {c['drop_hover']}; }}
QListWidget {{ border: 1px solid {c['border_soft']}; border-radius: 8px;
              background: {c['panel']}; padding: 4px; }}
QListWidget::item {{ padding: 8px 6px; border-bottom: 1px solid {c['item_line']};
                    color: {c['text']}; }}
QLineEdit {{ padding: 6px 8px; border: 1px solid {c['border']}; border-radius: 6px;
            background: {c['panel']}; color: {c['text']}; }}
QLineEdit::placeholder {{ color: {c['muted']}; }}
QFrame#rule {{ color: {c['border_soft']}; background: {c['border_soft']}; }}
QPushButton#primary {{
    background: {c['accent']}; color: {c['on_accent']}; font-weight: 600;
    padding: 9px 18px; border: 0; border-radius: 8px;
}}
QPushButton#primary:disabled {{ background: {c['accent_off']}; }}
QPushButton#primary:hover:enabled {{ background: {c['accent_hover']}; }}
QPushButton#secondary {{
    background: {c['panel']}; color: {c['accent']}; font-weight: 600;
    padding: 9px 16px; border: 1px solid {c['border']}; border-radius: 8px;
}}
QPushButton#secondary:disabled {{ color: {c['muted']}; border-color: {c['border_soft']}; }}
QPushButton#secondary:hover:enabled {{ background: {c['drop_hover']}; }}
QComboBox, QSpinBox {{ padding: 5px 8px; border: 1px solid {c['border']};
                      border-radius: 6px; background: {c['panel']}; color: {c['text']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']};
                              selection-background-color: {c['accent']};
                              selection-color: {c['on_accent']}; }}
QCheckBox {{ background: transparent; color: {c['muted']}; }}
QPlainTextEdit#log {{ border: 1px solid {c['border_soft']}; border-radius: 8px;
                     background: {c['panel']}; color: {c['text']};
                     font-family: "Menlo", "Consolas", monospace; font-size: 12px; }}
QMessageBox, QMessageBox QLabel {{ background: {c['bg']}; color: {c['text']}; }}
QDialog {{ background: {c['bg']}; color: {c['text']}; }}
"""


def _is_dark(app: QApplication) -> bool:
    """Decide light vs dark from the OS window colour's brightness."""
    col = app.palette().color(QPalette.Window)
    luminance = 0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue()
    return luminance < 128


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(SETTINGS_ORG)
    app.setStyleSheet(build_style(DARK if _is_dark(app) else LIGHT))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
