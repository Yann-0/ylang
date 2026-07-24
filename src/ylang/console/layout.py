"""Shared HTML layout and styles for the Ylang console."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from html import escape
from typing import Iterator

_CONSOLE_STYLES = """
  :root { color-scheme: dark; }
  body { font-family: system-ui, sans-serif; margin: 0; background: #0f1419; color: #e7ecf3; }
  a { color: #60a5fa; text-decoration: none; }
  a:hover { text-decoration: underline; }
  header { background: #1a2332; border-bottom: 1px solid #2a3548; padding: 0.75rem 2rem; }
  header nav { display: flex; gap: 0.85rem; flex-wrap: wrap; align-items: center; }
  header nav a { color: #9aa7b8; font-size: 0.9rem; }
  header nav a.active { color: #e7ecf3; font-weight: 600; }
  header .brand { font-weight: 700; color: #e7ecf3; margin-right: 0.75rem; }
  header .nav-group {
    display: inline-flex; gap: 0.85rem; flex-wrap: wrap; align-items: center;
  }
  header .nav-sep { color: #2a3548; user-select: none; }
  header details.nav-advanced { position: relative; }
  header details.nav-advanced > summary {
    list-style: none; cursor: pointer; color: #9aa7b8; font-size: 0.9rem;
    padding: 0.15rem 0.35rem;
  }
  header details.nav-advanced > summary::-webkit-details-marker { display: none; }
  header details.nav-advanced > summary::after { content: " ▾"; font-size: 0.75em; }
  header details.nav-advanced[open] > summary { color: #e7ecf3; }
  header details.nav-advanced .nav-advanced-menu {
    position: absolute; top: 100%; left: 0; z-index: 20; min-width: 11rem;
    margin-top: 0.35rem; padding: 0.4rem 0; background: #1a2332;
    border: 1px solid #2a3548; border-radius: 0.35rem;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
    display: flex; flex-direction: column; gap: 0;
  }
  header details.nav-advanced .nav-advanced-menu a {
    display: block; padding: 0.4rem 0.85rem; white-space: nowrap;
  }
  header details.nav-advanced .nav-advanced-menu a:hover { background: #1f2a3d; text-decoration: none; }
  header details.nav-advanced .nav-hint {
    display: block; padding: 0.25rem 0.85rem 0.5rem; color: #6b7a8d; font-size: 0.75rem;
  }
  main { padding: 2rem; max-width: 72rem; }
  h1 { margin-bottom: 0.25rem; }
  .subtitle { color: #9aa7b8; margin-bottom: 1.5rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .card { background: #1a2332; border-radius: 0.5rem; padding: 1rem 1.25rem; }
  .card .label { color: #9aa7b8; font-size: 0.85rem; }
  .card .value { font-size: 1.5rem; font-weight: 600; margin-top: 0.25rem; }
  section { margin-bottom: 2rem; }
  h2 { font-size: 1.1rem; margin-bottom: 0.75rem; }
  .panel { background: #1a2332; border-radius: 0.5rem; padding: 1.25rem; margin-bottom: 1.5rem; overflow-x: auto; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 1.5rem; }
  .chart-box { background: #1a2332; border-radius: 0.5rem; padding: 1rem; }
  canvas { max-height: 16rem; }
  .table-wrap { overflow-x: auto; max-width: 100%; }
  table { width: 100%; max-width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  .table-wrap table { table-layout: fixed; }
  th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a3548; overflow-wrap: anywhere; word-break: break-word; vertical-align: top; }
  th { color: #9aa7b8; font-weight: 500; }
  td code { word-break: break-all; white-space: pre-wrap; overflow-wrap: anywhere; }
  tr:hover td { background: #1f2a3d; }
  input, select, textarea, button {
    font: inherit; color: #e7ecf3; background: #0f1419; border: 1px solid #2a3548;
    border-radius: 0.35rem; padding: 0.5rem 0.75rem;
  }
  button, .btn {
    background: #2563eb; border-color: #2563eb; cursor: pointer; color: #fff;
    display: inline-block; padding: 0.5rem 1rem; border-radius: 0.35rem; text-decoration: none;
  }
  button:hover, .btn:hover { background: #1d4ed8; text-decoration: none; }
  button:disabled, .btn.is-loading, button.is-loading {
    opacity: 0.7; cursor: wait; pointer-events: none;
  }
  button.is-loading::after, .btn.is-loading::after {
    content: ""; display: inline-block; width: 0.85em; height: 0.85em; margin-left: 0.5em;
    border: 2px solid rgba(255,255,255,0.35); border-top-color: #fff; border-radius: 50%;
    vertical-align: -0.1em; animation: ylang-spin 0.7s linear infinite;
  }
  @keyframes ylang-spin { to { transform: rotate(360deg); } }
  .console-busy-overlay {
    display: none; position: fixed; inset: 0; z-index: 1000;
    background: rgba(15, 20, 25, 0.45); align-items: center; justify-content: center;
  }
  body.console-busy .console-busy-overlay { display: flex; }
  .console-busy-overlay .spinner {
    width: 2rem; height: 2rem; border: 3px solid #2a3548; border-top-color: #60a5fa;
    border-radius: 50%; animation: ylang-spin 0.7s linear infinite;
  }
  .btn-secondary { background: #374151; border-color: #374151; }
  .empty-state { border: 1px dashed #2a3548; text-align: center; padding: 2rem 1.5rem; }
  .empty-state h3 { margin-top: 0; margin-bottom: 0.5rem; }
  .empty-state p { color: #9aa7b8; max-width: 36rem; margin: 0.5rem auto 1.25rem; }
  .empty-state .cta-row { display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: center; }
  .suggestion { border-left: 3px solid #6366f1; padding-left: 1rem; margin-bottom: 1rem; }
  .suggestion.high { border-color: #ef4444; }
  .suggestion.medium { border-color: #f59e0b; }
  .badge { display: inline-block; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 999px; background: #2a3548; }
  .badge.ok { background: #14532d; color: #86efac; }
  .badge.warn { background: #713f12; color: #fcd34d; }
  .badge.err { background: #7f1d1d; color: #fca5a5; }
  pre { background: #0b0f14; padding: 1rem; border-radius: 0.35rem; overflow-x: auto; white-space: pre-wrap; }
  .form-row { margin-bottom: 1rem; }
  .form-row label { display: block; color: #9aa7b8; font-size: 0.85rem; margin-bottom: 0.25rem; }
  .form-row input, .form-row select, .form-row textarea { width: 100%; max-width: 32rem; }
  .settings-section {
    border: 1px solid #2a3548; border-radius: 0.5rem; padding: 1rem 1.25rem;
    margin: 0 0 1.25rem; max-width: 40rem;
  }
  .settings-section legend {
    padding: 0 0.5rem; color: #e7ecf3; font-weight: 600; font-size: 0.95rem;
  }
  .flash { padding: 0.75rem 1rem; border-radius: 0.35rem; margin-bottom: 1rem; }
  .flash.ok { background: #14532d; }
  .flash.err { background: #7f1d1d; }
  .hub-cta-row { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.5rem; }
  .domain-nav { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
  .domain-nav a.active { background: #2563eb; border-color: #2563eb; color: #fff; }
  .alert-panel { border-left: 3px solid #ef4444; }
  .settings-section summary { cursor: pointer; color: #e7ecf3; font-weight: 600; }
  .settings-section details > summary { list-style: none; margin-bottom: 0.75rem; }
  .settings-section details > summary::-webkit-details-marker { display: none; }
  .settings-section details > summary::after { content: " ▾"; font-size: 0.75em; color: #9aa7b8; }
  .settings-section details[open] > summary::after { content: " ▴"; }
"""

# (key, href, label) — used to build primary vs advanced nav
_NAV_CORE = (
    ("control", "/console/control", "Control"),
    ("overview", "/console", "Overview"),
    ("usage", "/console/usage", "Usage"),
    ("improver", "/console/improver", "Improver"),
)
_NAV_LIBRARY = (
    ("templates", "/console/templates", "Templates"),
    ("facts", "/console/facts", "Facts"),
    ("patterns", "/console/patterns", "Patterns"),
)
_NAV_OPTIMIZE = (
    ("proposals", "/console/proposals", "Proposals"),
)
_NAV_GATED = (
    ("experiments", "/console/experiments", "Experiments"),
    ("feedback", "/console/feedback", "Feedback"),
)
_NAV_SYSTEM = (
    ("settings", "/console/settings", "Parameters"),
)
_NAV_ADVANCED_ALWAYS = (
    ("data", "/console/data", "Data"),
    ("advisor", "/console/advisor", "Advisor"),
    ("ops", "/console/ops", "Ops"),
)
_NAV_SETUP = ("setup", "/console/setup", "Setup")

CHART_JS_SRC = "/console/static/chart.umd.min.js"

_CONSOLE_LOADING_SCRIPT = """
<script>
(() => {
  const busyClass = "console-busy";
  const loadingClass = "is-loading";
  let lastAsyncBtn = null;

  function setPageBusy(on) {
    document.body.classList.toggle(busyClass, on);
  }
  function setBtnLoading(el, on) {
    if (!(el instanceof HTMLElement)) return;
    el.classList.toggle(loadingClass, on);
    if (el instanceof HTMLButtonElement) el.disabled = on;
    if (on) el.setAttribute("aria-busy", "true");
    else el.removeAttribute("aria-busy");
  }
  window.ylangLoadingDone = function (target) {
    setPageBusy(false);
    setBtnLoading(target || lastAsyncBtn, false);
    lastAsyncBtn = null;
  };

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.noLoading !== undefined) return;
    setPageBusy(true);
    const submitter = event.submitter;
    if (submitter instanceof HTMLElement) setBtnLoading(submitter, true);
  });

  document.addEventListener("click", (event) => {
    const el = event.target instanceof Element
      ? event.target.closest("button, a.btn")
      : null;
    if (!(el instanceof HTMLElement) || el.dataset.noLoading !== undefined) return;
    if (el.classList.contains("param-remove") || el.classList.contains("icon-btn")) return;
    if (el instanceof HTMLAnchorElement) {
      if (el.getAttribute("href") && !el.getAttribute("href").startsWith("#")) {
        setPageBusy(true);
        el.classList.add(loadingClass);
      }
      return;
    }
    if (el instanceof HTMLButtonElement && el.type === "submit") return;
    lastAsyncBtn = el;
    setBtnLoading(el, true);
    setPageBusy(true);
  }, true);

  window.addEventListener("pageshow", () => {
    setPageBusy(false);
    document.querySelectorAll("." + loadingClass).forEach((node) => {
      setBtnLoading(node, false);
    });
  });
})();
</script>
"""


@dataclass(frozen=True)
class ConsoleNavContext:
    """Controls which nav items appear in primary vs Advanced.

    Routes still work when an item is hidden from primary nav (deep links OK).
    """

    experiments_enabled: bool = False
    edit_feedback_enabled: bool = False
    setup_complete: bool = False


_NAV_CONTEXT: ContextVar[ConsoleNavContext] = ContextVar(
    "ylang_console_nav",
    default=ConsoleNavContext(),
)


def get_console_nav_context() -> ConsoleNavContext:
    """Return the current console nav context for this request."""
    return _NAV_CONTEXT.get()


def configure_console_nav(context: ConsoleNavContext) -> Token[ConsoleNavContext]:
    """Set nav context for the current task; return a reset token."""
    return _NAV_CONTEXT.set(context)


def reset_console_nav(token: Token[ConsoleNavContext]) -> None:
    """Restore the previous nav context."""
    _NAV_CONTEXT.reset(token)


@contextmanager
def console_nav_scope(context: ConsoleNavContext) -> Iterator[ConsoleNavContext]:
    """Temporarily apply ``context`` for nested ``render_console_page`` calls."""
    token = configure_console_nav(context)
    try:
        yield context
    finally:
        reset_console_nav(token)


def _nav_anchor(
    key: str,
    href: str,
    label: str,
    *,
    active_nav: str,
    alert_badge: str | None,
) -> str:
    css = "active" if key == active_nav else ""
    badge = (
        f' <span class="badge warn">{escape(alert_badge)}</span>'
        if key == "patterns" and alert_badge
        else ""
    )
    return f'<a href="{href}" class="{css}">{escape(label)}{badge}</a>'


def _split_nav_items(
    context: ConsoleNavContext,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Build primary and advanced nav lists from feature flags / setup state."""
    primary: list[tuple[str, str, str]] = [
        *_NAV_CORE,
        *_NAV_LIBRARY,
        *_NAV_OPTIMIZE,
    ]
    advanced: list[tuple[str, str, str]] = list(_NAV_ADVANCED_ALWAYS)

    # Experiments / Feedback only appear in nav when their flags are on.
    # Deep links still work; pages show enable-flag empty states when off.
    for key, href, label in _NAV_GATED:
        enabled = (
            context.experiments_enabled
            if key == "experiments"
            else context.edit_feedback_enabled
        )
        if enabled:
            primary.append((key, href, label))

    if context.setup_complete:
        advanced.append(_NAV_SETUP)
    else:
        primary.append(_NAV_SETUP)

    primary.extend(_NAV_SYSTEM)
    return primary, advanced


def render_empty_state(
    *,
    title: str,
    body: str,
    primary_href: str | None = None,
    primary_label: str | None = None,
    secondary_html: str = "",
) -> str:
    """Render a centered empty-state panel with optional CTAs."""
    ctas: list[str] = []
    if primary_href and primary_label:
        ctas.append(
            f'<a class="btn" href="{escape(primary_href)}">{escape(primary_label)}</a>'
        )
    if secondary_html:
        ctas.append(secondary_html)
    cta_row = (
        f'<div class="cta-row">{"".join(ctas)}</div>' if ctas else ""
    )
    return f"""
<div class="panel empty-state">
  <h3>{escape(title)}</h3>
  <p>{escape(body)}</p>
  {cta_row}
</div>
"""


def render_console_page(
    *,
    title: str,
    body_html: str,
    active_nav: str = "overview",
    subtitle: str | None = None,
    extra_head: str = "",
    alert_badge: str | None = None,
) -> str:
    """Wrap page content in the shared console layout."""
    context = get_console_nav_context()
    primary, advanced = _split_nav_items(context)
    primary_html = "".join(
        _nav_anchor(key, href, label, active_nav=active_nav, alert_badge=alert_badge)
        for key, href, label in primary
    )
    advanced_open = ' open' if any(key == active_nav for key, _, _ in advanced) else ""
    advanced_links = "".join(
        _nav_anchor(key, href, label, active_nav=active_nav, alert_badge=alert_badge)
        for key, href, label in advanced
    )
    advanced_html = f"""
    <span class="nav-sep" aria-hidden="true">|</span>
    <details class="nav-advanced"{advanced_open}>
      <summary>Advanced</summary>
      <div class="nav-advanced-menu">
        {advanced_links}
      </div>
    </details>
"""
    subtitle_html = f'<p class="subtitle">{escape(subtitle)}</p>' if subtitle else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — Ylang Console</title>
<script src="{CHART_JS_SRC}"></script>
<style>{_CONSOLE_STYLES}</style>
{extra_head}
</head>
<body>
<div class="console-busy-overlay" aria-hidden="true" aria-live="polite">
  <div class="spinner" role="status" aria-label="Loading"></div>
</div>
<header>
  <nav>
    <span class="brand">Ylang</span>
    <span class="nav-group">{primary_html}</span>
    {advanced_html}
    <form method="post" action="/console/logout" style="margin-left:auto">
      <button type="submit" class="btn-secondary">Logout</button>
    </form>
  </nav>
</header>
<main>
  <h1>{escape(title)}</h1>
  {subtitle_html}
  {body_html}
</main>
{_CONSOLE_LOADING_SCRIPT}
</body>
</html>"""
