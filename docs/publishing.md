# Publishing documentation (GitHub Pages)

Operator docs are a **MkDocs Material** site. After they land on `main`, GitHub
Actions builds and publishes them to:

**https://yann-0.github.io/ylang/**

Repository: [Yann-0/ylang](https://github.com/Yann-0/ylang) (git root is the
`app/` tree).

## What gets published

| Path | On the site |
|------|-------------|
| `docs/*.md` | Pages listed in `mkdocs.yml` `nav` |
| `docs/images/console/*.png` | Portal screenshots (this folder must be committed) |
| `mkdocs.yml` | Theme, nav, `site_url` |

Nav-omitted historical files (`audit-and-roadmap.md`, `backlog*.md`,
`dead-code.md`) stay in git but are **not** in the sidebar. `mkdocs build
--strict` still succeeds (`omitted_files: info`).

## Local preview

```bash
cd app   # or the Yann-0/ylang clone root
pip install -e ".[docs]"
mkdocs serve          # http://127.0.0.1:8000
mkdocs build --strict
```

## CI workflow

[`.github/workflows/pages.yml`](https://github.com/Yann-0/ylang/blob/main/.github/workflows/pages.yml):

1. Trigger: push to `main` that touches `docs/**`, `mkdocs.yml`, `README.md`,
   `pyproject.toml`, or the workflow file; also **Run workflow**
   (`workflow_dispatch`).
2. `pip install -e ".[docs]"` then `mkdocs build --strict`.
3. Upload `site/` and deploy with `actions/deploy-pages`.

GitHub repo settings required once (repo admin):

- **Settings → Pages → Source:** GitHub Actions
- Workflow permission: `pages: write` and `id-token: write` (already in the YAML)

Until Pages is enabled, the `deploy` job stays yellow/failed even if `build`
is green.

## Screenshots

Portal PNGs are **not** generated in CI (no live Ylang + token). Capture on a
running HTTP instance before you commit:

```bash
python scripts/capture-console-screenshots.py
git add docs/images/console/*.png
```

Do not commit screenshots that show secrets, full prompt bodies, or Bearer
tokens. Login captures use an empty token field.

## After merge

1. Push (or merge) to `main`.
2. Wait for the **Docs** workflow (Actions tab).
3. Open https://yann-0.github.io/ylang/ — Portal:
   https://yann-0.github.io/ylang/portal/
   Configuration: https://yann-0.github.io/ylang/configuration/

CDN/cache can lag a minute. Hard-refresh if an old nav appears.
