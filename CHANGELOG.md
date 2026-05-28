# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the image-tag scheme is
documented in [docs/tagging.md](./docs/tagging.md).

## [Unreleased]

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
