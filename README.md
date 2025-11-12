# QC Asset Crawler

Small command‑line tool that scans shared media storage (SAN), finds new or changed assets (MXF, WAV, image sequences, etc.), and writes a lightweight QC sidecar file for each. Sidecars record whether an asset has been quality‑checked and, when available, link to the Trak asset‑tracking system.

> Non‑destructive by design: media files are never modified. Sidecars live under a hidden `.qc/` folder by default.

---

## Table of contents
- [Overview](#overview)
- [Key features](#key-features)
- [How it fits the workflow](#how-it-fits-the-workflow)
- [Repo layout](#repo-layout)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Common examples](#common-examples)
  - [CLI options](#cli-options)
  - [Sidecar storage modes](#sidecar-storage-modes)
- [Image sequence handling](#image-sequence-handling)
- [Hashing, fingerprints & caching](#hashing-fingerprints--caching)
- [Policy versioning & idempotency](#policy-versioning--idempotency)
- [Trak integration](#trak-integration)
- [Sidecar schema](#sidecar-schema)
- [Utilities](#utilities)
  - [`make_fake_seq.py`](#make_fake_seqpy)
  - [`qc_cleanup.py`](#qc_cleanuppy)
- [Logging](#logging)
- [Performance notes](#performance-notes)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview
- **Purpose:** Track QC state of media at scale with a tamper‑evident audit trail.
- **Outputs:** Small JSON sidecars per asset or sequence under `.qc/` (default) or alongside files.
- **Modes:** Automated nightly audits (mark new assets *pending*) and operator sign‑off runs (mark *pass*/*fail* with notes).

## Key features
- Cheap fingerprinting to skip unchanged content; deep content hash (BLAKE3, SHA‑256 fallback) when needed.
- Image‑sequence grouping with frame range, padding, gap detection, and a combined manifest hash.
- Policy versioning: bump the policy to force re‑QC across prior assets.
- Optional Trak syncing for assets that successfully resolve in the tracker.
- Hidden `.qc/` folder keeps workspaces clean on macOS/Linux/Windows.

## How it fits the workflow
- **Nightly (automated):** scan target roots, create/refresh sidecars, set `qc_result="pending"` when not yet reviewed.
- **Operator (manual):** confirm review with `--operator`, `--result pass|fail`, and an optional `--note`.

## Repo layout
```
qc-asset-tracker/
├─ qc_crawl.py                   # main CLI
├─ qc_cleanup.py                   # developer utility: remove sidecars & hash cache
├─ make_fake_seq.py              # developer utility: create synthetic image sequences
│
├─ requirements.txt
├─ requirements-dev.txt
├─ .env.example
├─ .gitignore
├─ .flake8
├─ .pre-commit-config.yaml
│
├─ src/
│   └─ qc_asset_crawler/
│       ├─ __init__.py           # package version
│       └─ shims.py              # console entry point wrappers
│
├─ tests/
│   ├─ test_version.py
│   └─ test_cli_help.py
│
├─ README.md
└─ CONTRIBUTING.md
```

## Quick start
```bash
# Example: nightly audit of a show root using sidecar subdir mode
python qc_crawl.py /eikon/disney/jobs \
  --workers 32 --sidecar-mode subdir

# Example: operator sign-off with a note
python qc_crawl.py /jobs/black_swan/mastering/dcp/ov \
  --operator alice --result pass \
  --note "Viewed in Clipster. Levels OK" \
  --sidecar-mode subdir

# Example: flag a failure
python qc_crawl.py /jobs/superman/subtitling/feature/ar/final \
  --operator bob --result fail \
  --note "Incorrect language code in XML."
```

## Installation
```bash
# (Recommended) create a virtual environment
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate

# install deps
pip install -r requirements.txt
```

## Environment Setup

The QC Asset Crawler uses a simple .env file to store environment-specific configuration (like Trak API keys or QC metadata defaults).
An example template is included as .env.example.

### Create your environment file
Copy the template and fill in your local details:
```bash
cp .env.example .env
```

### Edit .env
Set values appropriate to your environment:
```bash
TRAK_BASE_URL=https://qa-trak.eikongroup.io/api/v1/
TRAK_ASSET_TRACKER_API_KEY=!my-secret-api-key
LOG_LEVEL=INFO
```

### Verify it loads
The crawler loads environment variables automatically using python-dotenv, so no extra configuration is needed.
At runtime, your .env file is located relative to the executable (even in frozen builds):
```bash
dotenv.load_dotenv(find_data_file('.env'))
```
### Keep secrets safe
Your real .env should never be committed to version control — it’s already ignored in .gitignore.


## Usage
Run the crawler against one or more directory roots. Sidecars are written per discrete asset (single files) or per image sequence directory.

### Common examples
- Scan one folder, multithreaded hashing:
  ```bash
  python qc_crawl.py /SAN/show/010/plates --workers 16
  ```
- Force sidecars inline next to media:
  ```bash
  python qc_crawl.py /SAN/show/010/plates --sidecar-mode inline
  ```
- Operator pass with policy bump (forces re‑QC on next runs):
  ```bash
  export QC_POLICY_VERSION=2025.11.0
  python qc_crawl.py /SAN/show/010/deliverables --operator jane --result pass
  ```

### CLI options
```
usage: qc_crawl.py PATH [PATH ...] [options]

General:
  --workers N              Number of worker threads for hashing (default: CPU count)
  --log LEVEL              Logging level: DEBUG|INFO|WARN|ERROR (default: INFO)

QC metadata:
  --operator NAME          Operator performing the QC (records in sidecar)
  --result {pass,fail,pending}
                           QC outcome to record (default: pending)
  --note TEXT              Optional operator note

Sidecars:
  --sidecar-mode {subdir,dot,inline}
                           Where to store sidecars (default: subdir)

Tracking:
  --trak                   Enable Trak lookup and posting
  --trak-url URL           Trak base URL
  --trak-token TOKEN       Trak auth token (or set $TRAK_TOKEN)

Other:
  --version                Show tool version
  -h, --help               Show this help
```

### Sidecar storage modes
- `subdir` (default): `<media_root>/.qc/…`
- `dot`: hidden file alongside media (e.g. `clip.mxf.qc.json` under `.qc/`);
- `inline`: sidecar placed next to asset (e.g. `clip.mxf.qc.json`).

## Image sequence handling
The crawler groups files into sequences using a filename stem, numeric frame component and extension (e.g. `shot.087469.tif`). All frames in a sequence share a **combined manifest hash** and a single sidecar. The sidecar records:
- `base`, `ext`, `first`, `last`, `frame_count`, `frame_min`, `frame_max`, `pad`, `range_count`, `holes`, and a `cheap_fp` summary.

## Hashing, fingerprints & caching
- **Cheap fingerprint:** `{files, bytes, newest_mtime}` to detect unchanged content without re‑hashing.
- **Content hash:** BLAKE3 (fast) with SHA‑256 fallback; merged into a manifest hash for sequences.
- **Per‑folder cache:** `.qc.hashcache.json` to avoid recomputing known hashes.

## Policy versioning & idempotency
Re‑runs skip work unless bytes or **policy** change. Bumping `QC_POLICY_VERSION` forces a re‑QC sweep so prior sidecars are refreshed with the new policy context.

## Trak integration
- Looks up assets by path via `/asset/asset-search`.
- Posts QC results when `qc_result != "pending"` and an asset exists.
- During outages, lookups fail fast and sidecars remain `pending`; results can be retried later.

## Sidecar schema
Example (abridged):
```json
{
  "qc_id": "019a73e9-…",
  "qc_time": "2025-11-11T15:12:43.123456+00:00",
  "operator": "alice",
  "tool_version": "eikon-qc-marker/1.1.0",
  "policy_version": "2025.11.0",
  "asset_path": "/SAN/show/010/plates/lgt",
  "asset_id": "ASSET-1234",
  "content_hash": "blake3:c29b…",
  "qc_result": "pass",
  "notes": "Viewed in Clipster; levels OK",
  "sequence": {
    "base": "conjuring-last-rites_tlr-f1_dcin_las",
    "ext": "tif",
    "first": "…087460.tif",
    "last":  "…089929.tif",
    "frame_count": 117,
    "frame_min": 87460,
    "frame_max": 89929,
    "pad": 6,
    "range_count": 10,
    "holes": 23,
    "cheap_fp": {"files":117, "bytes":1234567890, "newest_mtime":1762870000}
  }
}
```

## Utilities

### `make_fake_seq.py`
Developer helper to generate a synthetic image sequence for testing scanners, gaps and padding.

**Usage**
```bash
python make_fake_seq.py \
  --out /tmp/fake_seq/shot_A \
  --start 87460 --frames 117 --pad 6 --ext tif \
  --holes 23 --ranges 10
```
**Options**
- `--out PATH` (required): output directory or prefix; will create missing dirs
- `--start N` (default: 1): first frame number
- `--frames N` (default: 100): total frames to generate
- `--pad N` (default: 4): zero‑padding width
- `--ext EXT` (default: tif): file extension (e.g. tif, dpx, exr, jpg, png)
- `--holes N` (default: 0): number of missing frames to simulate
- `--ranges N` (default: 1): number of contiguous ranges to simulate
- `--bytes N` (optional): size per file in bytes (writes random data)

### `qc_cleanup.py`
Utility to clean a workspace back to a “fresh” state by removing QC artifacts.

**Removes**
- `.qc/` directories (recursively)
- `*.qc.json` sidecars (inline mode)
- `.qc.hashcache.json` per‑folder hash caches
- `qc.sequence.json` (legacy/explicit sequence files)

**Usage**
```bash
# dry‑run first
python qc_cleanup.py /path/to/root --dry-run

# actually delete (non‑interactive)
python qc_cleanup.py /path/to/root --yes
```
**Options**
- `--yes`                 Proceed without prompting
- `--dry-run`             Show what would be deleted without deleting
- `--include-hidden`      Include hidden directories outside `.qc/`
- `--glob PATTERN`        Additional file glob(s) to remove (repeatable)
- `--workers N`           Parallelise deletions (default: 8)

## Logging
Set `--log DEBUG` for verbose diagnostics. Trak 401/403s are de‑duplicated to avoid log spam during outages.

## Performance notes
- Multithreaded hashing via `ThreadPoolExecutor`.
- Cheap fingerprint avoids full rescans; per‑folder cache speeds up revisits.
- Nightly runtime scales sub‑linearly with total project size.

## Roadmap
- HMAC signing for sidecar integrity
- Retry queue for pending Trak posts
- Extended xattr support

## License
TBD (internal).
