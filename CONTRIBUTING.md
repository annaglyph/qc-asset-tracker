# Contributing

Welcome to the **QC Asset Tracker** development guide.
This document describes the project structure, coding standards, workflows, and expectations for making changes.

The goal of this repository is to maintain a fast, deterministic, production-grade QC crawler with clean modular design and predictable behaviour across environments.

---

# 📁 Project Structure

The project follows a clean, modular layout:

```
src/qc_asset_crawler/
├── config.py          # Tool-wide configuration (versions, xattr key)
├── crawler.py         # Main crawl engine (workers, dispatch, coordination)
├── sequences.py       # Walk filesystem, detect sequences, summarise frames
├── hashing.py         # cheap_fp, deep hash, manifest hash
├── hashcache.py       # Read/write .qc.hashcache.json
├── sidecar.py         # Naming rules, schema + policy versions, read/write helpers
├── qcstate.py         # QC signature builder (qc_id, timestamps, schema)
├── trak_client.py     # HTTP client for Trak integration
└── shims.py           # Entry points for installed CLI commands
```

Top-level developer scripts:
```
qc_crawl.py             # Developer entrypoint (CLI → crawler)
qc_cleanup.py           # Cleanup utility for sidecars & hashcache
make_fake_seq.py        # Synthetic sequence generator for testing
```

Tests:
```
tests/
├── test_version.py
└── test_cli_help.py
```

---

# 🧭 Development Workflow

## 1. Clone and Install

```bash
git clone <repo-url>
cd qc-asset-tracker
pip install -e .
pip install -r requirements-dev.txt
cp .env.example .env
```

## 2. Activate pre-commit hooks

```bash
pre-commit install
```

Run on demand:

```bash
pre-commit run --all-files
```

## 3. Running the crawler locally

```bash
python qc_crawl.py --log DEBUG /path/to/root
```

Or via installed entrypoint:

```bash
qc-crawl --sidecar-mode subdir /path
```

## 4. Running tests

```bash
pytest
```

---

# 🧱 Coding Standards

## Python Style
- Code is formatted with **Black**.
- Linting is enforced via **flake8**.
- Imports should be grouped: stdlib → third-party → internal modules.

## Naming
- Modules use `snake_case`.
- Variables use meaningful, descriptive names (avoid one-letter names unless trivial e.g. `i`, `f`).
- Constants use `UPPER_SNAKE_CASE`.
- CLI flags should be short, unambiguous, and lowercase.

## Modules Should Have Single Responsibilities
- `sequences.py` → grouping + summaries
- `hashing.py` → content hashing
- `hashcache.py` → cache load/save
- `sidecar.py` → file naming + schema
- `qcstate.py` → QC metadata
- `crawler.py` → orchestration
- `trak_client.py` → external HTTP calls

## Sidecar Schema
All sidecars must include:
- `qc_id` (UUID7)
- `qc_time` (UTC ISO8601)
- `operator`
- `tool_version`
- `policy_version`
- `schema_version`
- `content_hash`
- `qc_result`
- `sequence` (always present; `null` for single-file assets)

---

# 🔄 Git Workflow

## Commit Messages
Use conventional commits where possible:

- `feat:` new feature (e.g., `feat: add schema_version to sidecar`)
- `fix:` bug fixes
- `refactor:` structural improvements without behaviour change
- `chore:` tooling or housekeeping

## Branching
- `main` is stable.
- Feature work is normally done in branches:
  - `feature/<name>`
  - `refactor/<name>`
  - `bugfix/<name>`

## Pull Requests
A good PR includes:
- Clear description of the problem and the solution
- Scope limited to one responsibility
- Green tests & pre-commit
- Updated docs if behaviour changes

---

# 🧪 Testing Guidelines

Tests should:
- Avoid filesystem dependencies unless absolutely necessary
- Prefer using temporary directories (`tmp_path` fixture in pytest)
- Assert only on documented behaviour, not internal implementation
- Cover sequence detection, hashing, sidecars, and cleanup behaviour

Example:

```python
def test_inline_sidecar_creation(tmp_path):
    asset = tmp_path / "test.exr"
    asset.write_bytes(b"dummy")

    # Run a minimal crawl
    from qc_asset_crawler import crawler
    qc = crawler.process_single_file(asset, operator="test")

    assert qc is not None
```

---

# 📦 Packaging

This project uses `pyproject.toml` with Setuptools.
Installed entrypoints are exposed via:

```toml
[project.scripts]
qc-crawl = "qc_asset_crawler.shims:crawl"
qc-clean = "qc_asset_crawler.shims:clean"
make-fake-seq = "qc_asset_crawler.shims:fake_seq"
```

---

# 🤝 Contributing

1. Create a new branch
2. Make incremental changes (small, reviewable steps)
3. Ensure tests and pre-commit hooks pass
4. Update documentation if needed
5. Open a Pull Request

Thank you for contributing to the QC Asset Tracker!
