"""Defense in depth for offline Python checks; systemd supplies OS isolation."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(os.environ["YLANG_CI_RUN"]).resolve()


def deny(event: str) -> None:
    """Retain the blocked event without recording application arguments."""
    with (ROOT / "logs/guard-denials.jsonl").open("a") as output:
        output.write(json.dumps({"event": event}) + "\n")
    raise PermissionError("Offline CI blocked " + event)


def guard(event: str, args: tuple) -> None:
    """Block Python network calls and access to production storage/settings."""
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        if getattr(args[0], "family", None) in (2, 10):
            deny(event)
    if event == "socket.getaddrinfo":
        deny(event)
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.path.realpath(os.fsdecode(args[0]))
        if path == "/srv/ylang/ylang.env" or path.startswith("/srv/ylang/data/"):
            deny("production file access")
    if event == "sqlite3.connect" and args[0] != ":memory:":
        path = os.path.realpath(os.fsdecode(args[0]))
        if not path.startswith(str(ROOT) + os.sep):
            deny("SQLite outside private run")


sys.addaudithook(guard)
