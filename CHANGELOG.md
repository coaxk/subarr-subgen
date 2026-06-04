# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the image-tag scheme is
documented in [docs/tagging.md](./docs/tagging.md).

## [v2026.05.3-r4] - 2026-06-05

### Added
- `0016-asr-path-and-kwargs` (v4.10, #131) — POST /asr accepts `path=` (read
  audio from a subgen-visible path, no upload) + `kwargs=<json>` (per-request
  override) and returns the sub over HTTP. The no-shared-scratch arena channel
  for subarr's tuning lab. kwargs folded into `generate_audio_hash` (fixes a
  latent dedup collision where variants differing only by kwargs returned the
  same cached result); task_id hash-based when kwargs present; `audio_file`
  optional; worker reads from `audio_path` without slurping into memory.
  Advertises `capabilities.asr_arena`.

### Changed
- `subarr_subgen_patch_rev` advertised on GET /queue: `v4.9` → `v4.10`.

## [v2026.05.3-r3] - 2026-06-04

### Added
- `0015-per-request-task` (v4.9, #131) — `task=transcribe|translate` query
  param on POST /batch overriding the global `TRANSCRIBE_OR_TRANSLATE` for one
  batch; advertises `capabilities.per_request_task`. Pairs with v4.8 kwargs so
  subarr's tuning-lab arena drives source-transcribe + candidate-translate over
  one path-based channel. Additive + backward-compatible (invalid/None task
  falls back to the global).

### Changed
- `subarr_subgen_patch_rev` advertised on GET /queue: `v4.8` → `v4.9`.

## [v2026.05.3-r2] - 2026-06-04

First image release since r1. r1's published image was pinned at the v4.2
patch set; every patch landed since (patch revs v4.3 → v4.8) had never been
built into a public image. This release brings
`ghcr.io/coaxk/subarr-subgen:latest` fully current.

### Added
- `0008-log-language-detection-probability` — surfaces Whisper's
  language-detection probability in logs.
- `0009-audio-language-override` (v4.3) — `audio_language_override` query
  param on POST /batch + `capabilities` block on GET /queue.
- `0010-queue-cancel` (v4.4) — `POST /queue/cancel?path=…` with structured
  not-cancellable reasons.
- `0011-robust-language-detection` (v4.5) — `POST /detect_language_robust`
  (N-chunk majority-vote + min-probability aggregate).
- `0012-curated-language-prompts` (v4.6) — curated per-language Whisper
  prompts via `SUBARR_SUBGEN_DEFAULT_PROMPTS`.
- `0013-safe-decode-preset` (v4.7) — hardened decode path so one malformed
  file can't wedge the worker.
- `0014-per-request-kwargs` (v4.8, #88) — `kwargs=<json>` query param on
  POST /batch overriding global + per-language `SUBGEN_KWARGS` for one
  batch (per-request wins); advertises `capabilities.per_request_kwargs`.
  Unblocks subarr's tuning-lab/tournament arena. Additive +
  backward-compatible.

### Changed
- `subarr_subgen_patch_rev` advertised on GET /queue: `v4.2` → `v4.8`.

## [v2026.05.3-r1] - 2026-05-28

### Added
- Initial repo skeleton: README, LICENSE (MIT), NOTICE (upstream
  attribution), `.gitattributes` with hard LF lock across all text files.
- Upstream submodule pinned to McCloudS/subgen@`b4fbc8d` (subgen
  `2026.05.3`).
- 7 patches extracted, applied, validated against the deployed
  `subgen_patched.py` ground-truth artefact:
  - `0001-per-language-kwargs` — `SUBGEN_KWARGS_LANG_<CODE>` env-var
    support, wired into 3 transcribe sites.
  - `0002-eager-model-load` — load + verify Whisper model on container
    start instead of lazily.
  - `0003-reverse-sort-transcribe-existing` — full-unit replace adding
    `?reverse=true` plus a structured counts dict.
  - `0004-batch-structured-response` — `/batch` returns
    `JSONResponse({counts}, status)` with 200/404 semantics.
  - `0005-gsq-return-str` — `gen_subtitles_queue` returns a dispatch
    string used by `_tally`.
  - `0006-fastapi-jsonresponse-import` — one-line import widening for
    0004.
  - `0007-deduplicated-queue-type-tracking-and-queue-endpoint` —
    `DeduplicatedQueue` tracks `path → type` + adds `GET /queue`.
- Tooling: `scripts/apply-patches.sh`, `scripts/build.sh`,
  `scripts/validate-patched.py` (compile + AST + text-marker gates),
  `scripts/upstream.pin`.
- Docker: `docker/Dockerfile` extends upstream with OCI labels for
  version provenance; supports `UPSTREAM_VERSION` + `PATCH_REV`
  build args.
- CI: PR validation, tag-triggered multi-arch release to GHCR, weekly
  upstream-drift detector with sticky issue creation.
- Docs: `docs/tagging.md`, `docs/developing-a-patch.md`,
  `docs/upstream-sync.md`.

### Notes
- Not yet released to GHCR — first tagged release will be `v2026.05.3-r1`.
- Smoke-tested locally: build script succeeds end-to-end, image boots,
  eager-load patch fires on startup (verified via container logs).
- Validator confirms all 7 patches land correctly via 11 structural gates.
