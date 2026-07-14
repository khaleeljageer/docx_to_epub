# FCM new-book notification (Option A: GitHub Action)

Sends a push notification to the Android app whenever a new monthly issue is
published, using **FCM topic messaging** (topic `new_book_added`) via the
**FCM HTTP v1 API**. No backend, no device tokens.

## How it fires

`publisher.py` (the desktop app) commits `booksdb.json` to
`tamilmarxist/MarxistTamilEbooks` via the GitHub Contents API. That push
triggers the workflow, which reads `books[0]` and POSTs to FCM.

```
publisher.py → commits booksdb.json (master)
      ↓ on: push, paths: booksdb.json
notify.yml → send_fcm.py → FCM v1 → topic "new_book_added"
      ↓
subscribed Android devices get the notification
```

## Files — deploy into the CONTENT repo (tamilmarxist/MarxistTamilEbooks)

| This repo (staging)      | → Target path in MarxistTamilEbooks   |
| ------------------------ | ------------------------------------- |
| `fcm-notify/notify.yml`  | `.github/workflows/notify.yml`        |
| `fcm-notify/send_fcm.py` | `.github/scripts/send_fcm.py`         |

These do **not** run from the `epub_maker` repo — `booksdb.json` lives in the
content repo, so the path-filtered trigger only matches there.

## One-time setup

1. **Firebase service-account key** — Firebase Console → Project Settings →
   Service Accounts → *Generate new private key*. Downloads a JSON file.
2. **GitHub secret** — in `tamilmarxist/MarxistTamilEbooks`:
   Settings → Secrets and variables → Actions → *New repository secret*
   - Name: `FCM_SERVICE_ACCOUNT`
   - Value: paste the **entire contents** of the JSON key file.

   The `project_id` is read from that JSON, so no separate project-id secret is
   needed. The key never ships in the desktop binary.

## Notification content

- **Title:** `புதிய இதழ் வெளியானது` (fixed, in `send_fcm.py`)
- **Body:** the issue's Tamil month-year title (`books[0].title`)
- **Data payload:** `bookid`, `title`, `epub`, `image` — for deep-linking on tap
- **Big picture:** `books[0].image` as the Android notification image

## Duplicate guard

The workflow checks out the last 2 commits and compares the newest `bookid`
against the previous `booksdb.json`. If it's unchanged (a re-publish or a
metadata-only edit of the same issue), no notification is sent.

## Testing

- **Dry run (no send):** run `send_fcm.py` locally with `DRY_RUN=1`,
  `FCM_SERVICE_ACCOUNT=<json>`, and `BOOKSDB=<path to a booksdb.json>` to print
  the exact message.
- **Live manual test:** after deploying, use the **Run workflow** button
  (workflow_dispatch) on the Actions tab. Note the duplicate guard won't skip a
  manual run unless `books[0]` matches the previous commit.

Requires: `google-auth`, `requests` (installed by the workflow).
