"""Load prompt collection CSV from URL or local path.

Scheduled refresh uses ``secure_fetch.SecureFetcher`` (HTTPS allowlist).
This helper remains for manual/local CSV loads and tests.
"""

from __future__ import annotations

from pathlib import Path

from ylang.importer.policy import SourcePolicyError, validate_fetch_url
from ylang.importer.secure_fetch import DEFAULT_FETCHER, FetchError

DEFAULT_PROMPTS_URL = (
    "https://raw.githubusercontent.com/f/prompts.chat/main/prompts.csv"
)


def load_csv_text(*, url: str | None = None, csv_path: Path | None = None) -> str:
    """Return CSV text from a local file or remote HTTPS URL."""
    if csv_path is not None:
        return csv_path.read_text(encoding="utf-8")
    target = url or DEFAULT_PROMPTS_URL
    if target.startswith("file://"):
        return Path(target.removeprefix("file://")).read_text(encoding="utf-8")
    if Path(target).exists():
        return Path(target).read_text(encoding="utf-8")
    try:
        source_id = None
        try:
            validate_fetch_url(target, source_id="prompts-chat")
            source_id = "prompts-chat"
        except SourcePolicyError:
            source_id = None
        response = DEFAULT_FETCHER.get(
            target,
            source_id=source_id,
            content_kind="csv",
        )
        return response.text()
    except (FetchError, SourcePolicyError, OSError) as exc:
        msg = f"failed to fetch prompts CSV from {target}: {exc}"
        raise OSError(msg) from exc
