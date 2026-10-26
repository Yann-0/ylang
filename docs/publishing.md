# Publishing documentation

Documentation is built and qualified on **stelsrv-d001** by the
[on-prem pipeline](ci.md). The candidate migration removes the GitHub Actions
Pages workflow. Administrator disablement of existing cloud workflows is a
separate approval and must precede any push that could trigger them.

The historical public site is <https://yann-0.github.io/ylang/>. Its existence
does not prove that current source has been built or published. The former
automatic GitHub Actions build/deploy instructions are superseded.

## Build and preview

Run these commands only in an approved isolated server workspace, from the
repository root containing `pyproject.toml` and `mkdocs.yml`:

```bash
pip install -e ".[docs]"
mkdocs build --strict
mkdocs serve
```

The controller instead installs from its reviewed offline wheelhouse and writes
the built site into that run's artifacts directory. Its manifest retains the
source commit, dependency identity, command, exit code, and timestamp.

## Publication approval

A passing docs build produces a local site artifact. Publishing it to any host,
pushing a Pages branch, or changing hosting configuration requires separate
approval. Do not reintroduce an Actions controller or cloud build scheduler.

Keep screenshots in `docs/images/console/`. Screenshot capture against a live
service requires its own approved scope; the qualification pipeline does not
capture private prompts, tokens, or production screens.

## Historical navigation and validation

Nav-omitted audit/closure files remain historical evidence. MkDocs currently
labels omitted files as informational and ignores several link-validation
categories. A strict successful build does not establish that every historical
link works.
