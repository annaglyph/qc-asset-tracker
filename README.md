# QC Asset Tracker

A fast, deterministic asset-scanning tool for generating QC sidecars, hashing media, detecting image sequences, and optionally integrating with Trak for asset registration.

Designed for high‑volume SAN/VFX environments, the QC Asset Tracker walks a directory tree, identifies media assets, computes fingerprints and hashes, creates structured sidecar metadata, and supports re‑runs via per‑directory hash caching.

This repository includes:
- A modular Python package (`qc_asset_crawler`) containing all crawler logic.
- A developer entrypoint script (`qc_crawl.py`) for running the crawler locally.
- Utility scripts:
  - `qc_cleanup.py` – remove QC artifacts for a clean re‑run.
  - `make_fake_seq.py` – generate synthetic EXR/DPX/TIFF sequences for testing.

---

## Features

- 🎞️ **Sequence detection**: EXR, DPX, JPEG, PNG, TIFF, TIF
- 🔍 **Cheap fingerprinting** + **deep hashing** using BLAKE3 (SHA‑256 fallback)
- 📁 **Three sidecar modes**: `inline`, `dot`, `subdir (.qc/)`
- 🧾 **Unified sidecar schema** with `schema_version` and `sequence: null` for singles
- 🚀 **Multithreaded crawling** with per-directory hash caching
- 🔗 Optional **Trak integration** (lookup & QC result posting)
- 🧹 **Cleanup utility** to remove all QC artifacts

---

## Installation

Clone the repo and install in editable mode:

```bash
pip install -e .
```

Install development tools:

```bash
pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and modify as needed:

```bash
cp .env.example .env
```

---

## Usage (Development)

### CLI

Run the crawler directly:

```bash
python qc_crawl.py [OPTIONS] ROOT
```

Example:

```bash
python qc_crawl.py --log DEBUG --sidecar-mode subdir /SAN/show/shot/renders
```

### Installed CLI (via `shims`)

If installed via `pip install .`, the following commands become available:

- `qc-crawl`
- `qc-clean`
- `make-fake-seq`

Example:

```bash
qc-crawl --sidecar-mode inline /mnt/renders
```

---

## CLI Options

```
usage: qc_crawl.py [-h] [--operator OPERATOR] [--workers WORKERS] [--log LOG]
                   [--min-seq MIN_SEQ]
                   [--sidecar-mode {inline,dot,subdir}]
                   [--result {pass,fail,pending}] [--note NOTE]
                   root

QC marker for media on a SAN (consolidated).

positional arguments:
  root                  Root path to crawl

options:
  -h, --help            show this help message and exit
  --operator OPERATOR   Operator name (defaults to $USER)
  --workers WORKERS     Number of worker threads
  --log LOG             Logging level
  --min-seq MIN_SEQ     Minimum number of frames to treat as a sequence
  --sidecar-mode        Where/how sidecars are written: inline, dot, or subdir
  --result              Force QC result override: pass, fail, pending
  --note NOTE           Optional operator note stored in the sidecar
```

---

## Sidecar JSON Schema

All sidecars follow a unified schema containing:
- Unique QC ID (`qc_id`)
- Timestamp (`qc_time`)
- Tool & policy version
- Schema version
- Asset path & optional Trak asset ID
- Content hash
- QC result (`pass`, `fail`, `pending`)
- Notes
- Sequence summary OR `null` for non-sequences

### Example – Sequence Sidecar

```json
{
  "asset_id": "12345",
  "asset_path": "//Mac/Shared/jobs/running_man/vfx/renders/feature/german/r2/dcin/xyz/2d/inserts/mono/4096x1716",

  "content_hash": "blake2b:f8e57495d797e14961d14d69847d5ccb641a08f6021f6cb0d10af24af914b1f2",
  "content_state": "modified",                      /* new | modified | unchanged */

  "notes": "",
  "operator": "night-crawler",

  "policy_version": "2025.11.0",

  "qc_id": "019a9227-2cb7-7015-91aa-518d1c14796b",
  "qc_result": "pending",                           /* pending | pass | fail */
  "qc_time": "2025-11-17T14:11:48.955360+00:00",

  "schema_version": "1.0.0",

  "sequence": {
    "base": "running-man_r2_german",
    "cheap_fp": {
      "bytes": 0,
      "files": 1038,
      "newest_mtime": 1762949063
    },
    "ext": "tif",
    "first": "running-man_r2_german.17726.tif",
    "frame_count": 1038,
    "frame_max": 198920,
    "frame_min": 17726,
    "holes": 180157,
    "last": "running-man_r2_german.198920.tif",
    "pad": 5,
    "range_count": 4
  },

  "tool_version": "eikon-qc-marker/1.1.0",

  // The key/values below may not be present when the initial sidecar is created by a nightly crawl.

  "last_valid_qc_id": "019a9227-2cb7-7015-91aa-518d1c14796b",
  "last_valid_qc_time": "2025-11-17T14:10:32.247275+00:00",
  "prev_content_hash": "blake2b:f0c53dbf84fa5d022ead3d2b9e3d1ad6a295c17ef7e07b39b15f118e5ebd10cd"

  "tracker_status": {
    "http_code": 401,
    "status": "unauthorized"
  }
}
```

### Example – Single File Sidecar

```json
{
  "asset_id": "12345",
  "asset_path": "//Mac/Shared/jobs/running_man/vfx/renders/feature/german/r2/dcin/xyz/2d/inserts/mono/4096x1716",

  "content_hash": "blake2b:f8e57495d797e14961d14d69847d5ccb641a08f6021f6cb0d10af24af914b1f2",
  "content_state": "modified",                      /* new | modified | unchanged */

  "notes": "",
  "operator": "night-crawler",

  "policy_version": "2025.11.0",

  "qc_id": "019a9227-2cb7-7015-91aa-518d1c14796b",
  "qc_result": "pending",                           /* pending | pass | fail */
  "qc_time": "2025-11-17T14:11:48.955360+00:00",

  "schema_version": "1.0.0",

  "sequence": null,

  "tool_version": "eikon-qc-marker/1.1.0",

  // The key/values below may not be present when the initial sidecar is created by a nightly crawl.

  "last_valid_qc_id": "019a9227-2cb7-7015-91aa-518d1c14796b",
  "last_valid_qc_time": "2025-11-17T14:10:32.247275+00:00",
  "prev_content_hash": "blake2b:f0c53dbf84fa5d022ead3d2b9e3d1ad6a295c17ef7e07b39b15f118e5ebd10cd",

  "tracker_status": {
    "http_code": 401,
    "status": "unauthorized"
  }
}
```

### Sidecar Modes

- **inline**: `file.exr.qc.json`
- **dot**: `.file.exr.qc.json`
- **subdir**: `.qc/file.exr.qc.json`

Sequence sidecars follow the same mode and use the filename from:

```python
sidecar.get_side_name_sequence()  # from .env or default "qc.sequence.json"
```

---

## Cleanup Utility

Remove all QC-generated artifacts from a folder:

```bash
python qc_cleanup.py /path --dry-run
python qc_cleanup.py /path --yes
```

Removes:
- Inline sidecars (`*.qc.json`)
- Dot-mode sidecars (`.*.qc.json`)
- Sequence sidecars (`qc.sequence.json`, `.qc.sequence.json`)
- Hash cache (`.qc.hashcache.json`)
- Subdir (`.qc/`) folders

---

## Developer Notes

Development is structured around small, clear modules:

```
src/qc_asset_crawler/
├── crawler.py          # main crawl engine
├── sequences.py        # walk filesystem & detect sequences
├── hashing.py          # cheap_fp + deep hashing + manifest hashing
├── hashcache.py        # read/write .qc.hashcache.json
├── sidecar.py          # naming, schema version, sidecar helpers
├── qcstate.py          # QC signature (schema, policy, operator)
├── trak_client.py      # Trak HTTP client
├── config.py           # tool-wide configuration
└── shims.py            # entry points for installed CLI
```

Top‑level tools:
```
qc_crawl.py             # local developer entrypoint
qc_cleanup.py           # cleanup tool
make_fake_seq.py        # synthetic image sequence generator
```

### Testing

```bash
pytest
```

### Linting & Formatting

```bash
pre-commit run --all-files
```

---

## License

Internal EIKON project — not for external distribution.
