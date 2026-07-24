"""Server-rendered console page builders."""

from ylang.console.page_modules.overview import (
    render_overview_page,
)
from ylang.console.page_modules.control import (
    render_control_page,
)
from ylang.console.page_modules.usage import (
    render_usage_page,
)
from ylang.console.page_modules.settings import (
    render_settings_page,
)
from ylang.console.page_modules.templates import (
    render_templates_page,
)
from ylang.console.page_modules.facts import (
    render_facts_page,
)
from ylang.console.page_modules.patterns import (
    render_patterns_page,
)
from ylang.console.page_modules.experiments import (
    render_experiments_page,
)
from ylang.console.page_modules.proposals import (
    render_proposals_page,
)
from ylang.console.page_modules.ops import (
    render_ops_page,
)

__all__ = [
    render_overview_page,
    render_control_page,
    render_usage_page,
    render_settings_page,
    render_templates_page,
    render_facts_page,
    render_patterns_page,
    render_experiments_page,
    render_proposals_page,
    render_ops_page,
]
