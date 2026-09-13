"""prompts.chat / awesome-chatgpt-prompts CSV adapter (CC0 prompt data)."""

from __future__ import annotations

from collections.abc import Mapping

from ylang.importer.convert import convert_rows, parse_csv_rows
from ylang.importer.source_types import ParsedUpstreamItem

PROMPTS_CHAT_OWNER_REPOS: tuple[tuple[str, str], ...] = (
    ("f", "prompts.chat"),
    ("f", "awesome-chatgpt-prompts"),
)
PROMPTS_CHAT_CSV_NAME = "prompts.csv"
PROMPTS_CHAT_REF = "main"
LAYOUT_HINT = "prompts.csv at repository root"


class PromptsChatAdapter:
    """Parse the structured prompts.csv catalog."""

    source_id = "prompts-chat"
    layout_hint = LAYOUT_HINT

    def select_paths(self, tree_paths: list[str]) -> list[str]:
        """Import only the catalog CSV."""
        return [path for path in tree_paths if path == PROMPTS_CHAT_CSV_NAME]

    def parse(
        self,
        files: Mapping[str, str],
        *,
        revision: str,
    ) -> list[ParsedUpstreamItem]:
        """Parse act/prompt CSV rows."""
        csv_text = files.get(PROMPTS_CHAT_CSV_NAME)
        if csv_text is None:
            for key, value in files.items():
                if key.endswith("prompts.csv") or key == "csv":
                    csv_text = value
                    break
        if csv_text is None:
            msg = "prompts-chat payload missing prompts.csv"
            raise ValueError(msg)
        rows = parse_csv_rows(csv_text)
        parsed: list[ParsedUpstreamItem] = []
        for spec in convert_rows(rows):
            parsed.append(
                ParsedUpstreamItem(
                    upstream_item_id=spec.template_id,
                    title=spec.name,
                    body=spec.body,
                    canonical_url=(
                        f"https://github.com/f/prompts.chat/blob/{revision}/prompts.csv"
                    ),
                    metadata={
                        "params": [
                            {
                                "name": param.name,
                                "description": param.description,
                                "default": param.default,
                            }
                            for param in spec.params
                        ],
                        "adapter": self.source_id,
                    },
                )
            )
        return parsed


def prompts_chat_raw_csv_url(owner: str, repo: str, revision: str) -> str:
    """Return the raw CSV URL for a prompts.chat lineage revision."""
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{revision}/{PROMPTS_CHAT_CSV_NAME}"
