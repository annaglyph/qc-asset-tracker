# QC Asset Crawler – Repository Documentation Bundle

This repository contains:
- `README.md` — project overview and usage guide
- `CONTRIBUTING.md` — developer workflow, code style, and branching policy
- base Python package structure with `__init__.py` and versioning stub
- optional developer quality-of-life tooling (pre-commit hooks, linting)

---

## CONTRIBUTING.md

### Overview
We welcome internal contributions. Keep commits clean and descriptive. Avoid committing generated QC data.

### Branching Model
- `main` → stable production branch
- `dev` → integration and testing branch
- feature branches → `feature/<ticket_or_topic>`

**Example:**
```
git checkout -b feature/hashcache-refactor dev
```

### Commit Conventions
Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
```
feat: add new image sequence hashing strategy
fix: handle missing .qc.hashcache.json gracefully
chore: bump dependencies
```

### Code Style
- PEP 8 compliant (enforced by black + flake8)
- Typing encouraged: use Python 3.10+ type hints
- Docstrings: Google or NumPy style

**Example:**
```python
def scan_path(path: Path) -> list[Path]:
    """Scan for valid media assets within a directory."""
    ...
```

### Testing
Use pytest with fixtures under `/tests`. Tests should be idempotent and create files only under `/tmp`.

```
pytest -v
```

### Pull Requests
1. Rebase from `dev` before raising PRs.
2. Run `pre-commit run --all-files`.
3. Tag maintainers in PR description.

### Versioning
Semantic versioning (semver) pattern `MAJOR.MINOR.PATCH`. Version lives in:
```
qc_asset_crawler/__init__.py
```
```python
__version__ = "0.1.0"
```

### Linting & Hooks
Install pre-commit hooks:
```bash
pip install pre-commit && pre-commit install
```
`.pre-commit-config.yaml` includes:
- black
- flake8
- isort
- end-of-file-fixer
- trailing-whitespace

### Dev Dependencies
```
pip install -r requirements-dev.txt
```
Additions beyond runtime requirements:
- pytest
- black
- flake8
- pre-commit

### Continuous Integration
Recommended: GitLab CI YAML pipeline stub (optional):
```yaml
stages: [lint, test]

lint:
  stage: lint
  script:
    - pre-commit run --all-files

pytest:
  stage: test
  script:
    - pytest -v
```

---

## Repository Skeleton
```
qc-asset-crawler/
├── qc_asset_crawler/
│   ├── __init__.py
│   ├── qc_asset_crawler.py        # main crawler (hashing, sequences, trak logic)
│
├── make_fake_seq.py               # dev utility: fake image sequences
├── qc-clean.py                    # dev utility: clean QC metadata
├── requirements.txt
├── .gitignore
├── .pre-commit-config.yaml
├── README.md
├── CONTRIBUTING.md
└── tests/
    ├── __init__.py
    ├── test_crawler_core.py
```

---

## Next Steps
- Copy README and CONTRIBUTING into your repo root.
- Initialize pre-commit: `pre-commit install`
- Optionally add a `CHANGELOG.md` for versioned releases.

---

_This bundle provides a ready-to-push internal repo setup consistent with EIKON tooling standards._
