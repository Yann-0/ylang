"""Unit tests for console navigation IA and empty-state helpers."""

from __future__ import annotations

from ylang.console.layout import (
    ConsoleNavContext,
    console_nav_scope,
    render_console_page,
    render_empty_state,
)
from ylang.console.pages import render_experiments_page, render_templates_page
from ylang.console.pages_full import render_feedback_page
from ylang.console.template_list import TemplateListFilters, TemplateListPage


def test_primary_nav_includes_control() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_console_page(title="Overview", body_html="<p>x</p>")
    primary_chunk = html.split('class="nav-advanced"', 1)[0]
    assert "Control" in primary_chunk
    assert 'href="/console/control"' in primary_chunk


def test_primary_nav_hides_gated_flags_by_default() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_console_page(title="Overview", body_html="<p>x</p>")
    # Gated items are absent from nav entirely when flags are off (deep links OK)
    assert 'class="nav-advanced"' in html
    assert 'href="/console/experiments"' not in html
    assert 'href="/console/feedback"' not in html
    assert 'href="/console/control"' in html
    primary_chunk = html.split('class="nav-advanced"', 1)[0]
    assert "Experiments" not in primary_chunk
    assert "Feedback" not in primary_chunk
    assert "Control" in primary_chunk
    assert "Overview" in primary_chunk
    assert "Parameters" in primary_chunk


def test_primary_nav_shows_experiments_and_feedback_when_enabled() -> None:
    ctx = ConsoleNavContext(
        experiments_enabled=True,
        edit_feedback_enabled=True,
        setup_complete=True,
    )
    with console_nav_scope(ctx):
        html = render_console_page(title="Overview", body_html="<p>x</p>")
    primary_chunk = html.split('class="nav-advanced"', 1)[0]
    assert "Experiments" in primary_chunk
    assert "Feedback" in primary_chunk
    # Setup moves to Advanced when complete
    assert "Setup" not in primary_chunk
    advanced_chunk = html.split('class="nav-advanced"', 1)[1]
    assert "Setup" in advanced_chunk


def test_setup_stays_primary_when_incomplete() -> None:
    with console_nav_scope(ConsoleNavContext(setup_complete=False)):
        html = render_console_page(title="Overview", body_html="<p>x</p>")
    primary_chunk = html.split('class="nav-advanced"', 1)[0]
    assert "Setup" in primary_chunk


def test_advanced_opens_when_active_nav_is_nested() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_console_page(
            title="Data",
            body_html="<p>x</p>",
            active_nav="data",
        )
    assert 'class="nav-advanced" open' in html or 'class="nav-advanced"open' in html


def test_render_empty_state_includes_cta() -> None:
    html = render_empty_state(
        title="Nothing here",
        body="Do the thing.",
        primary_href="/console/settings",
        primary_label="Go to Settings",
    )
    assert "Nothing here" in html
    assert 'href="/console/settings"' in html
    assert "Go to Settings" in html
    assert "empty-state" in html


def test_experiments_empty_state_when_disabled() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_experiments_page([], [], experiments_enabled=False)
    assert "Experiments are off" in html
    assert "Enable in Settings" in html
    assert 'href="/console/settings"' in html


def test_experiments_empty_state_when_enabled_no_variants() -> None:
    with console_nav_scope(ConsoleNavContext(experiments_enabled=True)):
        html = render_experiments_page([], [], experiments_enabled=True)
    assert "No variants yet" in html
    assert "Create variant" in html


def test_feedback_empty_state_when_disabled() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_feedback_page([], edit_feedback_enabled=False)
    assert "Edit feedback is off" in html
    assert "Enable in Settings" in html
    assert "YLANG_CAPTURE_EDIT_FEEDBACK=1" in html
    assert "edit_feedback" in html


def test_feedback_empty_state_when_enabled_no_events() -> None:
    with console_nav_scope(ConsoleNavContext(edit_feedback_enabled=True)):
        html = render_feedback_page([], edit_feedback_enabled=True)
    assert "No feedback events yet" in html
    assert "YLANG_CAPTURE_EDIT_FEEDBACK=1" in html


def _empty_template_page(**filter_kwargs: object) -> TemplateListPage:
    filters = TemplateListFilters(**filter_kwargs)  # type: ignore[arg-type]
    return TemplateListPage(rows=(), total=0, page=1, per_page=25, filters=filters)


def test_templates_empty_state_when_library_empty() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_templates_page(_empty_template_page())
    assert "No templates yet" in html
    assert "empty-state" in html
    assert 'href="#template-create"' in html
    assert 'id="template-create" open' in html or 'id="template-create"open' in html
    assert "Advanced" in html
    primary_chunk = html.split('class="nav-advanced"', 1)[0]
    assert "Templates" in primary_chunk


def test_templates_empty_state_when_filters_match_nothing() -> None:
    with console_nav_scope(ConsoleNavContext()):
        html = render_templates_page(
            _empty_template_page(unused_only=True, source="user")
        )
    assert "No matching templates" in html
    assert 'href="/console/templates"' in html
    assert "Clear filters" in html
    assert 'id="template-create" open' not in html


def test_console_page_includes_loading_overlay() -> None:
    html = render_console_page(title="Overview", body_html="<p>x</p>")
    assert "console-busy-overlay" in html
    assert "ylangLoadingDone" in html
    assert "console-busy" in html
