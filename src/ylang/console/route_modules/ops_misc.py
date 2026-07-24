"""Console routes: ops misc."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    RedirectResponse,
    Response,
)

from ylang.console.advisor import generate_advisor_reply
from ylang.console.context import (
    ConsoleContext,
)
from ylang.console.proposals import (
    filter_already_applied,
)
from ylang.console.hooks_monitor import tail_hook_log
from ylang.console.import_ops import import_json_payload
from ylang.console.pages import (
    render_ops_page,
)
from ylang.console.pages_full import (
    render_advisor_page,
    render_health_page,
    render_setup_page,
)
from ylang.console.provider_health import check_providers
from ylang.usage.async_ops import run_store_sync


def register_ops_misc_routes(ctx: ConsoleContext) -> None:
    """Register ops_misc console routes."""
    @ctx.server.custom_route("/console/advisor", methods=["GET", "POST"])
    async def console_advisor(request: Request) -> Response:
        reply = None
        question = ""
        setting_proposals = None
        if request.method == "POST":
            form = await request.form()
            question = str(form.get("question", "")).strip()
            if question:
                result = await run_store_sync(
                    lambda: generate_advisor_reply(
                        question,
                        store=ctx.deps.store,
                        engine=ctx.engine,
                        settings=ctx.effective_settings(),
                        runtime_store=ctx.runtime_store,
                    )
                )
                reply = result.text
                setting_proposals = filter_already_applied(
                    result.setting_proposals,
                    ctx.deps.store._connection,
                )
        return ctx.render(
            lambda: render_advisor_page(
                reply=reply,
                question=question,
                setting_proposals=setting_proposals,
            )
        )


    @ctx.server.custom_route("/console/setup", methods=["GET"])
    async def console_setup(_request: Request) -> Response:
        checks = ctx.setup_checks()
        return ctx.render(lambda: render_setup_page(checks=checks))


    @ctx.server.custom_route("/console/health", methods=["GET"])
    async def console_health(_request: Request) -> Response:
        return ctx.render(
            lambda: render_health_page(
                providers=check_providers(ctx.effective_settings()),
                hook_lines=tail_hook_log(),
            )
        )


    @ctx.server.custom_route("/console/ops", methods=["GET"])
    async def console_ops(request: Request) -> Response:
        message = request.query_params.get("msg")
        return ctx.render(
            lambda: render_ops_page(
                storage_path=str(ctx.settings.resolved_storage_path()),
                message=message,
            )
        )


    @ctx.server.custom_route("/console/ops/backup", methods=["GET"])
    async def console_ops_backup(_request: Request) -> Response:
        source = ctx.settings.resolved_storage_path()
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        with sqlite3.connect(source) as src, sqlite3.connect(tmp_path) as dst:
            src.backup(dst)
        return FileResponse(
            tmp_path,
            filename="ylang-backup.db",
            media_type="application/octet-stream",
        )


    @ctx.server.custom_route("/console/ops/export", methods=["GET"])
    async def console_ops_export(_request: Request) -> Response:
        templates = []
        for summary in ctx.deps.library.list():
            template = ctx.deps.library.recall(summary.template_id)
            if template is None:
                continue
            templates.append(
                {
                    "template_id": template.template_id,
                    "name": template.name,
                    "body": template.body,
                    "params": [
                        {
                            "name": p.name,
                            "description": p.description,
                            "default": p.default,
                        }
                        for p in template.params
                    ],
                    "source": template.source,
                    "visibility": template.visibility,
                    "tags": list(template.tags),
                }
            )
        facts = [
            {
                "fact": fact.fact,
                "scope": fact.scope,
                "workspace": fact.workspace,
                "created_at": fact.created_at.isoformat(),
            }
            for fact in ctx.deps.memory.recall(limit=10_000)
        ]
        payload = {"version": 1, "templates": templates, "facts": facts}
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        json.dump(payload, tmp, indent=2)
        tmp_path = Path(tmp.name)
        tmp.close()
        return FileResponse(
            tmp_path,
            filename="ylang-export.json",
            media_type="application/json",
        )


    @ctx.server.custom_route("/console/ops/import", methods=["POST"])
    async def console_ops_import(request: Request) -> Response:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return RedirectResponse("/console/ops?msg=No+file", status_code=303)
        raw = await upload.read()  # type: ignore[union-attr]
        payload = json.loads(raw.decode("utf-8"))
        templates, facts = import_json_payload(ctx.deps.library, ctx.deps.memory, payload)
        return RedirectResponse(
            f"/console/ops?msg=Imported+{templates}+templates+and+{facts}+facts",
            status_code=303,
        )


    @ctx.server.custom_route("/console/ops/restore", methods=["POST"])
    async def console_ops_restore(request: Request) -> Response:
        form = await request.form()
        if str(form.get("confirm", "")).strip() != "RESTORE":
            return RedirectResponse("/console/ops?msg=Type+RESTORE+to+confirm", status_code=303)
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return RedirectResponse("/console/ops?msg=No+file", status_code=303)
        raw = await upload.read()  # type: ignore[union-attr]
        target = ctx.settings.resolved_storage_path()
        safety = target.with_suffix(f".pre-restore{target.suffix}")
        tmp_path = Path(tempfile.mkstemp(suffix=".db")[1])
        try:
            tmp_path.write_bytes(raw)
            with sqlite3.connect(tmp_path) as probe:
                tables = {
                    row[0]
                    for row in probe.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            required = {"usage", "templates", "facts"}
            if not required.issubset(tables):
                return RedirectResponse(
                    "/console/ops?msg=Invalid+Ylang+database+file",
                    status_code=303,
                )
            if target.is_file():
                target.replace(safety)
            tmp_path.replace(target)
        except OSError:
            return RedirectResponse("/console/ops?msg=Restore+failed", status_code=303)
        finally:
            if tmp_path.is_file():
                tmp_path.unlink(missing_ok=True)
        reconnected = ctx.reconnect_stores_after_restore()
        if reconnected:
            msg = (
                "Database+restored+and+connections+reloaded.+"
                "Run+sudo+systemctl+restart+ylang+if+pages+look+stale."
            )
        else:
            msg = (
                "Database+restored.+Run+sudo+systemctl+restart+ylang+to+reload+all+handles."
            )
        return RedirectResponse(f"/console/ops?msg={msg}", status_code=303)

