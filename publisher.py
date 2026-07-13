"""Publish a generated e-book to the MarxistTamilEbooks GitHub repo.

Uses the GitHub REST Contents API (no local git clone, no git binary), so it
works from a packaged desktop app on any OS. For a given month/year it:

  1. uploads  books/<slug>.epub
  2. generates + uploads  images/<slug>.webp   (via cover.make_cover)
  3. prepends (or updates) the matching entry in  booksdb.json

A fine-grained Personal Access Token with "Contents: read and write" on the
target repo is required.

Public API:
    GitHubPublisher(token, ...).publish(epub_bytes, month, year) -> dict
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid

import cover

DEFAULT_OWNER = "tamilmarxist"
DEFAULT_REPO = "MarxistTamilEbooks"
DEFAULT_BRANCH = "master"

API_ROOT = "https://api.github.com"


class PublishError(RuntimeError):
    """Raised when a GitHub API call fails."""


def _noop(_msg: str) -> None:
    pass


class GitHubPublisher:
    def __init__(self, token, owner=DEFAULT_OWNER, repo=DEFAULT_REPO,
                 branch=DEFAULT_BRANCH, log=None):
        if not token or not token.strip():
            raise ValueError("A GitHub token is required.")
        self.token = token.strip()
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.log = log or _noop

    # --- low-level API ----------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{API_ROOT}/repos/{self.owner}/{self.repo}/{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "EpubMaker-Publisher")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except (ValueError, AttributeError):
                pass
            raise PublishError(
                f"GitHub API {method} {path} failed: {exc.code} {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise PublishError(f"Network error contacting GitHub: {exc.reason}") from exc

    def _get_contents(self, path: str) -> dict | None:
        """Return the contents object for `path` (with sha + base64 content),
        or None if the file does not exist."""
        try:
            return self._request("GET", f"contents/{path}?ref={self.branch}")
        except PublishError as exc:
            if "404" in str(exc):
                return None
            raise

    def _put_file(self, path: str, data: bytes, message: str) -> None:
        existing = self._get_contents(path)
        body = {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": self.branch,
        }
        if existing and existing.get("sha"):
            body["sha"] = existing["sha"]
            self.log(f"Updating {path} …")
        else:
            self.log(f"Creating {path} …")
        self._request("PUT", f"contents/{path}", body)

    # --- booksdb.json -----------------------------------------------------

    def _raw_url(self, path: str) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/raw/{self.branch}/{path}"

    def _update_booksdb(self, title, date, image_url, epub_url, epub_path) -> str:
        """Insert or update the entry for this book. Returns the bookid used."""
        self.log("Updating booksdb.json …")
        current = self._get_contents("booksdb.json")
        if current is None:
            raise PublishError("booksdb.json not found in the repository.")

        db = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
        books = db.setdefault("books", [])

        # Match an existing entry by its epub filename so re-publishing the
        # same month updates in place instead of duplicating.
        epub_name = epub_path.rsplit("/", 1)[-1]
        existing = next(
            (b for b in books if str(b.get("epub", "")).endswith("/" + epub_name)),
            None,
        )

        if existing is not None:
            bookid = existing.get("bookid") or str(uuid.uuid4()).upper()
            existing.update(title=title, date=date, bookid=bookid,
                            image=image_url, epub=epub_url)
            self.log(f"Updated existing booksdb entry ({bookid}).")
        else:
            bookid = str(uuid.uuid4()).upper()
            books.insert(0, {  # newest first, matching current ordering
                "title": title,
                "date": date,
                "bookid": bookid,
                "image": image_url,
                "epub": epub_url,
            })
            self.log(f"Added new booksdb entry ({bookid}).")

        new_content = json.dumps(db, ensure_ascii=False, indent=4) + "\n"
        self._request("PUT", "contents/booksdb.json", {
            "message": f"Update booksdb.json for {title}",
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
            "sha": current["sha"],
        })
        return bookid

    # --- orchestration ----------------------------------------------------

    def publish(self, epub_bytes: bytes, month: int, year: int) -> dict:
        """Upload the epub + generated cover and update booksdb.json.

        Returns a dict with slug, title, date, bookid, and the two raw URLs.
        """
        if not epub_bytes:
            raise ValueError("epub_bytes is empty.")

        slug = cover.slug_for(month, year)
        title = cover.tamil_title(month, year)
        date = cover.date_label(month, year)
        epub_path = f"books/{slug}.epub"
        cover_path = f"images/{slug}.webp"

        self.log(f"Publishing “{title}” to {self.owner}/{self.repo}@{self.branch}")

        self.log("Generating cover …")
        cover_bytes = cover.make_cover(month, year)

        self._put_file(epub_path, epub_bytes, f"Add {slug}.epub ({title})")
        self._put_file(cover_path, cover_bytes, f"Add cover for {title}")

        epub_url = self._raw_url(epub_path)
        image_url = self._raw_url(cover_path)
        bookid = self._update_booksdb(title, date, image_url, epub_url, epub_path)

        self.log("Done.")
        return {
            "slug": slug,
            "title": title,
            "date": date,
            "bookid": bookid,
            "epub_url": epub_url,
            "image_url": image_url,
        }


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Publish an epub to MarxistTamilEbooks.")
    parser.add_argument("epub", help="path to the .epub file")
    parser.add_argument("month", type=int, help="month number 1-12")
    parser.add_argument("year", type=int, help="year e.g. 2026")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub PAT (or set GITHUB_TOKEN)")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args()

    with open(args.epub, "rb") as fh:
        epub_data = fh.read()

    pub = GitHubPublisher(args.token, owner=args.owner, repo=args.repo,
                          branch=args.branch, log=print)
    result = pub.publish(epub_data, args.month, args.year)
    print(json.dumps(result, ensure_ascii=False, indent=2))
