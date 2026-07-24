"""Console HTTP route registrars by domain."""

from ylang.console.route_modules.api import register_api_routes
from ylang.console.route_modules.experiments import register_experiments_routes
from ylang.console.route_modules.facts import register_facts_routes
from ylang.console.route_modules.feedback_data import register_feedback_data_routes
from ylang.console.route_modules.ops_misc import register_ops_misc_routes
from ylang.console.route_modules.overview import register_overview_routes
from ylang.console.route_modules.patterns import register_patterns_routes
from ylang.console.route_modules.proposals import register_proposals_routes
from ylang.console.route_modules.settings_control import register_settings_control_routes
from ylang.console.route_modules.static_auth import register_static_auth_routes
from ylang.console.route_modules.templates import register_templates_routes

__all__ = [
    "register_api_routes",
    "register_experiments_routes",
    "register_facts_routes",
    "register_feedback_data_routes",
    "register_ops_misc_routes",
    "register_overview_routes",
    "register_patterns_routes",
    "register_proposals_routes",
    "register_settings_control_routes",
    "register_static_auth_routes",
    "register_templates_routes",
]
