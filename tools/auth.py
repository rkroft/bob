"""Make the Gmail token that `bob scan --gmail` needs.

`gmail_source.py` reads `~/.bob/google_token.json` and refreshes it, but nothing
in this repo ever created it — so `/bob-setup`'s instruction to "place them at
~/.bob/google_token.json" could not be followed by anyone, including the author.
This is the missing half.

**Read-only, and only mail.** The scope is `gmail.readonly` and nothing else.
Bob does not send from this credential: drafts land through the user's own
Claude connector (Plugin MVP §4.8), so the token that reads six years of mail
can never write a message. That separation is worth keeping even though it means
two mechanisms.

**Nothing here reaches the author.** The client secret and the token are the
user's, created in their own Google Cloud project, living on their own disk at
0600. There is no Bob OAuth app to verify, no CASA assessment, and no cap on
users, because there is no shared application (§3.2).
"""
from __future__ import annotations

import os
import stat
import sys
import warnings
from pathlib import Path

# The google libraries emit four EOL/TLS FutureWarnings on this Python, which
# buried the only text that matters -- the walkthrough. A setup command whose
# instructions scroll off the top has failed at the one thing it does.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

BOB_HOME = Path(os.environ.get("BOB_HOME", Path.home() / ".bob"))
CLIENT_SECRET = Path(os.environ.get(
    "BOB_GOOGLE_CLIENT_SECRET", BOB_HOME / "google_client_secret.json"))
TOKEN = Path(os.environ.get("BOB_GOOGLE_TOKEN", BOB_HOME / "google_token.json"))

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

HOW_TO_GET_A_CLIENT_SECRET = f"""
No client secret found at:
  {CLIENT_SECRET}

This is the one step Bob cannot do for you — Google requires the application
asking for your mail to be one you own. Ten minutes, once, free:

  1. console.cloud.google.com -> create a project (any name)
  2. APIs & Services -> Library -> enable "Gmail API"
  3. APIs & Services -> OAuth consent screen -> External
  4. On that same screen, PUBLISH THE APP -- set it to "In production".
     This matters more than it looks. Left in "Testing", Google expires the
     refresh token every 7 days and you re-authorize weekly, forever. In
     production it persists. The price is a one-time "Google hasn't verified
     this app" screen, which you click past, and a 100-user cap you will
     never reach, because the only user is you.
  5. Credentials -> Create credentials -> OAuth client ID
     -> Application type: Desktop app
  6. Download the JSON and save it as:
       {CLIENT_SECRET}

Then run this again.

Not willing to do that? You do not have to. Export your mail with Google
Takeout instead and run `bob scan --mbox <path>` — no project, no credential,
no consent screen. It is slower to obtain and it is a snapshot rather than a
live source, and it is otherwise the same Bob.
""".strip()


def _secure(path: Path) -> None:
    """0600 on the token, 0700 on its directory.

    It grants read access to every message in a mailbox. Default umask would
    leave it world-readable on a shared machine.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    if path.exists():
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def authorize(client_secret: Path = CLIENT_SECRET,
              token: Path = TOKEN) -> str:
    """Run the consent flow and write the token. Returns the address it is for.

    Opens a browser and waits on a loopback redirect, so it needs a human and a
    desktop session. That is the whole reason it is a separate command rather
    than something the scan does on demand: a scan should never surprise anyone
    with a consent screen.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not client_secret.exists():
        raise SystemExit(HOW_TO_GET_A_CLIENT_SECRET)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    _secure(token)
    token.write_text(creds.to_json(), encoding="utf-8")
    _secure(token)

    # Prove it works before claiming it does. A token that authorizes but
    # cannot read is a failure the user should hear about now, not on the
    # first scan twenty minutes in.
    who = build("gmail", "v1", credentials=creds).users().getProfile(
        userId="me").execute()["emailAddress"]
    return who


def main(argv=None) -> int:
    if TOKEN.exists() and "--force" not in (argv or sys.argv[1:]):
        print(f"A token already exists at {TOKEN}.\n"
              f"`bob scan --gmail` will use it. Re-run with --force to replace it.")
        return 0
    who = authorize()
    print(f"\nAuthorized {who}.")
    print(f"Token written to {TOKEN} (read-only, mail only, 0600).")
    print("\nNext: bob scan --gmail --principal", who)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
