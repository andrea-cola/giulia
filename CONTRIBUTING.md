# Contributing to giulia

## Definition of Done

A change is **not done** until all five commands exit `0` on your machine, in
order. CI runs the exact same sequence; running it locally first is the
difference between a green PR and a red one.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Single-command shortcut:

```bash
make ci-local
```

`make ci-local` runs the four commands above in order and hard-fails on the
first red one. Run it before every `git push`.

---

## Development Setup

giulia uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone <repo>
cd giulia
uv sync          # install all deps including dev group
make hooks       # install pre-commit hooks (ruff + pyright on every commit)
```

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (any recent version)

---

## Code Style

- **Formatter / linter:** [ruff](https://docs.astral.sh/ruff/), configured in
  `pyproject.toml`. Line length 88. Rules: E, F, I, UP, B.
- **Type checker:** [pyright](https://github.com/microsoft/pyright) in
  `standard` mode. All public function signatures must be fully annotated.
- **Imports:** Use `from __future__ import annotations` in every module.
- **Docstrings:** All public functions and classes must have a docstring.
  Include an `Example::` block for non-trivial functions.

```python
async def mint_token(*, sub: str, scopes: list[str]) -> tuple[str, int]:
    """Mint an audience-bound JWT.

    Example::

        token, ttl = mint_token(sub="client-1", scopes=["agent:invoke"])
    """
    ...
```

---

## Adding a new layer

giulia is organised around **layers** (auth, registry, delegation, …).
Each layer lives in `giulia/agents/<layer>/`. When adding a new one:

1. Create `giulia/agents/<layer>/` with an `__init__.py` that re-exports the
   public surface.
2. Update `docs/layers.md` with the layer's contract and reference
   implementation.

---

## Pull Request Process

1. Branch from `main`.
2. Make your changes. Run `make ci-local` — all four checks must pass.
3. Open a PR with a clear description of *what* changed and *why*.
4. Address review feedback.

For larger changes (new layers, architectural modifications) please open an
issue first to discuss the approach.

---

## Releasing to PyPI

Releases are fully automated via `ci.yaml`. To ship a new version:

1. Bump the version in `packages/giulia/pyproject.toml` (the pre-commit `bump-version` hook does this automatically on every staged commit to `packages/giulia/giulia/`).
2. Commit and push to `main`.
3. The `release` job in `ci.yaml` runs after a green lint + typecheck, creates the `v<version>` tag, builds the wheel, and publishes to PyPI via OIDC trusted publishing — no token required.

> **Note:** OIDC trusted publishing must be configured once on PyPI at
> `pypi.org/manage/project/giulia/settings/publishing/` — add a GitHub Actions
> publisher pointing to this repository and the `ci.yaml` workflow.

---

## License

By contributing you agree that your contributions will be licensed under the
same license as this project.
