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

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QFrame, QSizePolicy,
)

from docx_to_epub import parse_articles, build_epub, Article

APP_NAME = "DOCX to EPUB maker"


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


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(640, 640)

        self._articles: list[Article] = []
        self._docx_path: Path | None = None
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
        self.make_btn = QPushButton("Create EPUB…")
        self.make_btn.setObjectName("primary")
        self.make_btn.setEnabled(False)
        self.make_btn.clicked.connect(self.create_epub)
        btn_row.addWidget(self.status)
        btn_row.addWidget(self.make_btn)
        root.addLayout(btn_row)

        self.setStyleSheet(STYLE)

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
        QMessageBox.information(
            self, APP_NAME,
            f"Done!\n\nSaved EPUB with {len(self._articles)} article"
            f"{'s' if len(self._articles) != 1 else ''} to:\n{out_path}",
        )

    def _on_build_failed(self, msg: str):
        self.status.setText("")
        self.make_btn.setEnabled(True)
        self._error("Could not build the EPUB", msg)

    def _error(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg)


STYLE = """
QWidget { font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; color: #1a202c; }
QLabel#muted { color: #6b7280; font-size: 12px; }
QLabel#found { font-weight: 600; margin-top: 4px; }
QLabel#drop {
    border: 2px dashed #cbd5e0; border-radius: 12px; background: #fbfcfe;
    color: #2b6cb0; font-size: 15px;
}
QLabel#drop[hover="true"] { border-color: #2b6cb0; background: #eef4fb; }
QListWidget { border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; padding: 4px; }
QListWidget::item { padding: 8px 6px; border-bottom: 1px solid #f0f2f5; }
QLineEdit { padding: 6px 8px; border: 1px solid #cbd5e0; border-radius: 6px; background: #fff; }
QFrame#rule { color: #e2e8f0; }
QPushButton#primary {
    background: #2b6cb0; color: #fff; font-weight: 600;
    padding: 9px 18px; border: 0; border-radius: 8px;
}
QPushButton#primary:disabled { background: #9db8d6; }
QPushButton#primary:hover:enabled { background: #255992; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
