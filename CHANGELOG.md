# CHANGELOG
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses **Unreleased** until we tag a real release.

---------------------------------

## **[Unreleased] – 2025-11-17**

### Added
- **Full integration test for `crawler.run()`**, covering:
  - Sequence + single-file processing
  - Sidecar writing
  - QC signature creation
  - Trak posting
  - Interaction between hash cache, cheap fingerprinting, and summarisation
- New **unit tests** for:
  - `process_single_file` and `process_sequence` sticky `asset_id` behaviour
  - Correct handling of Trak failures (401/404) without clearing existing `asset_id`
  - Ensuring `content_state` transitions work as expected on re-render
- Added **comprehensive sequence helper tests**:
  - `is_sequence_candidate`
  - `seq_key`
  - `group_sequences`
  - `summarize_frames` (holes, ranges, pad, invalid names)

### Changed
- **Improved `content_state` semantics:**
  - `"new"` is now used for first-seen content
  - `"modified"` only used when previous content existed and the hash changed
  - `"unchanged"` preserved where applicable
- **`asset_id` is now sticky:**
  - Existing sidecar `asset_id` is preserved when Trak is unavailable or responds without an asset match
  - Only overridden by CLI `--asset-id` or successful Trak lookup
- **Updated crawler logic in both single-file and sequence workflows to use the new decision-tree:**
  - CLI override → Trak → existing sidecar → null

### Improved
- Hardened crawler behaviour to avoid:
  - Clearing metadata when Trak is offline
  - Marking first-seen content as `"modified"`
  - Losing historical linkage between SAN content and Trak
- Test suite now includes >30 passing tests and covers:
  - Sequence detection
  - Hashcache behaviour
  - QC summary output
  - Sticky asset-ID logic
  - Integration of the entire crawler pipeline

### Notes

- README update pending to reflect new `content_state` semantics and sticky `asset_id` behaviour.
- Trak integration tests deferred until new API endpoints (POST sidecar & path search) are available.

---------------------------------

## **[Unreleased] – 2025-11-14**

### Added
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

### Changed
- **Nightly crawl behaviour**
  - Content changes no longer generate new `qc_id`s.
  - Nightly runs now ONLY reset `qc_result` to `"pending"` and update `content_state`.
  - `qc_id` is preserved unless a human QC is performed.
- **Sequence hashing optimisation**
  - When sequence frames are unchanged, operator QC reuses the stored `content_hash`.
  - Avoids unnecessary deep hashing on large sequences.

### Improved
- **Atomic writes for sidecars (`*.qc.json`)**
  - Sidecars are now written via `tmp → fsync → os.replace`.
  - Eliminates corruption risk from crashes or partial writes.
  - Maintains hidden attribute on Windows.
- **Atomic writes for `.qc.hashcache.json`**
  - Hash cache now uses the same atomic write pattern for consistency and safety.

### Maintenance
- Normalised logic between file and sequence QC paths for:
  - Change detection
  - State preservation
  - QC event propagation
- Added robust path handling for sidecar and sequence roots during missing detection.
- Improved logging:
  - `"Marked missing: N"` summary at end of crawl
  - Clearer differentiation between marked vs skipped assets

---------------------------------

## **[Unreleased] – 2025-11-13**

## **Major Refactor & Architecture Consolidation**

### **Migrated project to a modular package structure under `src/qc_asset_crawler/`**

- Added dedicated modules:
  - `crawler.py` – crawl engine, workers, dispatch
  - `sequences.py` – media walking, grouping, summaries
  - `hashing.py` – cheap_fp, deep hashing, manifest hashing
  - `hashcache.py` – .qc.hashcache.json load/save
  - `sidecar.py` – sidecar naming, schema, policy
  - `qcstate.py` – QC signature builder
  - `trak_client.py` – Trak HTTP operations
  - `config.py` – tool-wide configuration
  - `shims.py` – console entrypoints for installed scripts
- Cleaned `"qc_crawl.py"`, turning it into a thin CLI wrapper over the crawler engine
- Extracted all functionality from monolithic script into cohesive, testable modules
- Introduced a clear separation of responsibilities across modules

## **Sidecar Schema Enhancements**
- Added `schema_version` field (`1.0.0`) to all sidecars
- Ensured `sequence` is always present (`null` for single-file assets)
- Added environment-variable-driven overrides for:
  - `QC_SCHEMA_VERSION`
  - `QC_SIDE_SUFFIX_FILE`
  - `QC_SIDE_NAME_SEQUENCE`
  - `QC_POLICY_VERSION`

## **Improved Sidecar & Hashcache Handling**
- Unified naming conventions through helpers in `sidecar.py` & `hashcache.py`
- Sidecar location modes fully supported:
  - `inline
  - `dot
  - `subdir` (`.qc/`)
- Updated `qc_cleanup.py` to:
  - Use naming from `sidecar` and `hashcache`
  - Correctly remove dot-mode sequence files
  - Remove `.qc/` in subdir mode
  - Support dry-run and reflect new schema

## **CLI Enhancements**

- Added `--asset-id` option to explicitly assign Trak asset IDs per run
  - Skips Trak lookup if provided
  - Enables perfect integration with FileRunner and VFX workflows

- Normalised all CLI flags across entrypoints
- Updated help text, README, and examples

## **Documentation Overhaul**
- Fully rewritten README.md, including:
  - Modernised project overview
  - Accurate module layout
  - Updated CLI options
  - Updated sidecar schema examples
  - Updated workflow notes & usage patterns
- Fully rewritten CONTRIBUTING.md, including:
  - Coding standards
  - Dev workflow
  - PR guidelines
  - Module responsibilities
  - Testing strategy
- Cleaned `.gitignore`, removed egg-info, ensured `.env` is excluded

## **Testing & Tooling Improvements**
- Ensured project is stable under:
  - `pytest`
  - `pre-commit` (Black, flake8, whitespace cleanup)
- Added test scaffolding for future expansion
- Ensured consistent version management via `__init__.py`

## **Behavioural Stability**
- All refactors were behaviour-preserving
- All sidecar generation, hashing, and sequence grouping retain original semantics
- All improvements are additive and forward-compatible
