"""Console page renderers."""

from __future__ import annotations

from html import escape

from ylang.console.layout import render_console_page

def render_ops_page(*, storage_path: str, message: str | None = None) -> str:
    """Render operational shortcuts (backup, export, import)."""
    flash = f'<div class="flash ok">{escape(message)}</div>' if message else ""
    body = f"""
{flash}
<p class="subtitle">Operational helpers. Storage: <code>{escape(storage_path)}</code></p>
<div class="panel">
  <h2>Backup</h2>
  <p>Download a point-in-time SQLite backup.</p>
  <a class="btn" href="/console/ops/backup">Download backup</a>
</div>
<div class="panel">
  <h2>Export</h2>
  <p>Export templates and facts as JSON.</p>
  <a class="btn" href="/console/ops/export">Download export</a>
</div>
<div class="panel">
  <h2>Import</h2>
  <p>Import templates and facts from a prior JSON export.</p>
  <form method="post" action="/console/ops/import" enctype="multipart/form-data">
    <input type="file" name="file" accept="application/json,.json" required>
    <button type="submit" style="margin-top:1rem">Import JSON</button>
  </form>
</div>
<div class="panel">
  <h2>Restore</h2>
  <p>Replace the live database with an uploaded <code>.db</code> backup. Type <strong>RESTORE</strong> to confirm.</p>
  <p class="subtitle">After restore, Ylang attempts to reconnect SQLite handles. If pages look stale, run
  <code>sudo systemctl restart ylang</code> and verify with <code>ylang doctor</code>.</p>
  <form method="post" action="/console/ops/restore" enctype="multipart/form-data">
    <div class="form-row"><label>Backup file</label><input type="file" name="file" accept=".db,application/octet-stream" required></div>
    <div class="form-row"><label>Confirm</label><input name="confirm" placeholder="RESTORE" required></div>
    <button type="submit" class="btn-secondary">Restore database</button>
  </form>
</div>
<div class="panel">
  <h2>Usage digest</h2>
  <p>Digests are CLI/cron only — the console does not send email. Enable the digest
  flag under <a href="/console/settings">Settings</a>, then schedule:</p>
  <pre>ylang usage digest --last-days 7
# force desktop notify (needs DISPLAY + notify-send):
ylang usage digest --last-days 7 --notify
# cron example (Mon 09:00, shared env + DB):
# 0 9 * * 1 sg ylang -c 'set -a &amp;&amp; source /srv/ylang/ylang.env &amp;&amp; set +a &amp;&amp; ylang usage digest --last-days 7'</pre>
</div>
<div class="panel">
  <pre>ylang backup --output ~/ylang-backup.db
ylang export --output ~/ylang-export.json
ylang import --input ~/ylang-export.json
ylang doctor
sudo systemctl restart ylang   # after restore or code deploy</pre>
</div>
"""
    return render_console_page(title="Ops", body_html=body, active_nav="ops")

