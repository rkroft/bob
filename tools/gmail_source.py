"""Gmail implementation of the MailSource interface.

This is the shipped Gmail source, reachable from the public `bob scan --gmail`
command — not a scoring-only harness. It reads a read-only OAuth token from
`~/.bob/google_token.json` and a client secret from
`~/.bob/google_client_secret.json` by default; set BOB_GOOGLE_TOKEN /
BOB_GOOGLE_CLIENT_SECRET to point at different locations (that's how the
author keeps her own setup, elsewhere on disk).
"""

from __future__ import annotations

import base64
import os
import re
from email.utils import getaddresses
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mail_source import Message, Thread  # noqa: E402

BOB_HOME = Path.home() / ".bob"
TOKEN = Path(os.environ.get("BOB_GOOGLE_TOKEN", BOB_HOME / "google_token.json"))
CLIENT_SECRET = Path(
    os.environ.get("BOB_GOOGLE_CLIENT_SECRET", BOB_HOME / "google_client_secret.json")
)
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

MISSING_TOKEN_MSG = (
    "missing Gmail token. Set BOB_GOOGLE_TOKEN (and BOB_GOOGLE_CLIENT_SECRET) "
    "to point at your credentials, or place them at ~/.bob/google_token.json "
    "and ~/.bob/google_client_secret.json."
)

def _addrs(header: str | None) -> list[str]:
    return _named(header)[0]


def _named(header: str | None) -> tuple:
    """(addresses, display names) — parallel lists.

    `getaddresses` handles quoting and commas-inside-names correctly, which the
    old regex split did not: `"Okafor, Dana" <dana@x>` used to become two
    recipients. Names were discarded entirely, which is why graph nodes read
    `mlee` rather than `Marcus Lee`.
    """
    if not header:
        return [], []
    pairs = [(n, a) for n, a in getaddresses([header]) if a]
    return [a for _, a in pairs], [n for n, _ in pairs]


def _decode(data: str | None) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_for_text(part: dict, out: list[str], depth: int = 0) -> None:
    """Collect text/plain, falling back to text/html stripped of tags."""
    if depth > 8:
        return
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    if mime == "text/plain" and body.get("data"):
        out.append(_decode(body["data"]))
    elif mime == "text/html" and body.get("data") and not out:
        out.append(re.sub(r"<[^>]+>", " ", _decode(body["data"])))
    for sub in part.get("parts", []) or []:
        _walk_for_text(sub, out, depth + 1)


class GmailSource:
    def __init__(self) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not TOKEN.exists():
            raise SystemExit(MISSING_TOKEN_MSG)
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN.write_text(creds.to_json())
            else:
                raise SystemExit(
                    "token invalid and not refreshable. Re-authenticate and "
                    "refresh BOB_GOOGLE_TOKEN (or ~/.bob/google_token.json)."
                )
        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._principal: str | None = None

    def principal(self) -> str:
        if self._principal is None:
            self._principal = self.svc.users().getProfile(userId="me").execute()["emailAddress"].lower()
        return self._principal

    # Gmail has an index; asking it about one person is a single request.
    # `last_direct_contact` reads this to choose between asking per person and
    # walking the whole mailbox. MboxSource does not set it: a local file has
    # no index, and walking it is cheap.
    cheap_search = True

    def search(self, query: str, limit=None) -> Sequence[str]:
        """`limit=None` pages until Gmail runs out.

        500 ids per request, which is the API's maximum. It was 100, and on a
        broad query -- `roster` asks for five years of a whole mailbox -- that
        is hundreds of round trips before the caller learns how much work it
        has. Search is still cheap next to `fetch`, which costs one call per
        thread, but "cheap" stopped being true at that scale.
        """
        ids: list[str] = []
        page = None
        while limit is None or len(ids) < limit:
            resp = (
                self.svc.users().threads()
                .list(userId="me", q=query,
                      maxResults=500 if limit is None else min(500, limit - len(ids)),
                      pageToken=page)
                .execute()
            )
            ids.extend(t["id"] for t in resp.get("threads", []))
            page = resp.get("nextPageToken")
            if not page:
                break
        return ids if limit is None else ids[:limit]

    def fetch(self, thread_ids: Sequence[str], include_bodies: bool = True) -> Sequence[Thread]:
        fmt = "full" if include_bodies else "metadata"
        out: list[Thread] = []
        for tid in thread_ids:
            try:
                raw = self.svc.users().threads().get(userId="me", id=tid, format=fmt).execute()
            except Exception:
                continue
            out.append(self._to_thread(raw, include_bodies))
        return out

    def _to_thread(self, raw: dict, include_bodies: bool) -> Thread:
        msgs: list[Message] = []
        for m in raw.get("messages", []):
            payload = m.get("payload", {})
            hdrs = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

            body: str | None = None
            if include_bodies:
                chunks: list[str] = []
                _walk_for_text(payload, chunks)
                body = "\n".join(chunks)[:20000]

            ts = m.get("internalDate")
            date = (
                datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).replace(tzinfo=None)
                if ts else None
            )

            to_a, to_n = _named(hdrs.get("to"))
            cc_a, cc_n = _named(hdrs.get("cc"))
            from_a, from_n = _named(hdrs.get("from"))

            msgs.append(Message(
                id=m["id"],
                from_addr=from_a[0] if from_a else hdrs.get("from", ""),
                from_name=from_n[0] if from_n else "",
                to_addrs=to_a,
                to_names=to_n,
                cc_addrs=cc_a,
                cc_names=cc_n,
                subject=hdrs.get("subject", ""),
                date=date,
                body_text=body,
                is_calendar_invite=(
                    "text/calendar" in str(payload.get("mimeType", ""))
                    or "invite.ics" in str(hdrs.get("content-type", ""))
                    or bool(hdrs.get("x-google-calendar-event-id"))
                ),
                is_bulk=bool(
                    hdrs.get("list-unsubscribe")
                    or hdrs.get("list-id")
                    or (hdrs.get("precedence", "").lower() in {"bulk", "list", "junk"})
                ),
            ))
        return Thread(id=raw["id"], messages=msgs)
