# CHANGELOG
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses **Unreleased** until we tag a real release.

---

## **[Unreleased] – 2025-11-14**

### ✨ Added
- **Content state model (`content_state`)**
  Introduced precise content-state tracking for all assets and sequences:
  - `"unchanged"` — content matches previous hash
  - `"modified"` — content hash changed (new frames, removed frames, edits)
  - `"missing"` — media no longer present on disk (single-file or whole sequence)
- **Sequence-aware missing detection**
  - Sequences are now marked `"missing"` when all frames or single file(s) disappear but the sidecar remains.
  - Uses `base` + `ext` to identify expected frame names.
- **QC event tracking (`last_valid_qc_id`, `last_valid_qc_time`)**
  - Operator QC (`--result`) now registers a new explicit QC event.
  - Sidecar records the most recent human QC verdict independently of nightly crawls.

### 🛠️ Changed
- **Nightly crawl behaviour**
  - Content changes no longer generate new `qc_id`s.
  - Nightly runs now ONLY reset `qc_result` to `"pending"` and update `content_state`.
  - `qc_id` is preserved unless a human QC is performed.
- **Sequence hashing optimisation**
  - When sequence frames are unchanged, operator QC reuses the stored `content_hash`.
  - Avoids unnecessary deep hashing on large sequences.

### 🔒 Improved
- **Atomic writes for sidecars (`*.qc.json`)**
  - Sidecars are now written via `tmp → fsync → os.replace`.
  - Eliminates corruption risk from crashes or partial writes.
  - Maintains hidden attribute on Windows.
- **Atomic writes for `.qc.hashcache.json`**
  - Hash cache now uses the same atomic write pattern for consistency and safety.

### 🧹 Maintenance
- Normalised logic between file and sequence QC paths for:
  - Change detection
  - State preservation
  - QC event propagation
- Added robust path handling for sidecar and sequence roots during missing detection.
- Improved logging:
  - `"Marked missing: N"` summary at end of crawl
  - Clearer differentiation between marked vs skipped assets
