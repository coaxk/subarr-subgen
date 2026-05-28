# subarr-subgen

Pre-built [McCloudS/subgen](https://github.com/McCloudS/subgen) with the patches
[subarr](https://github.com/coaxk/subarr) requires.

## What this is

Subarr orchestrates [subgen](https://github.com/McCloudS/subgen) to drive
Whisper-based subtitle generation across your library. To do that cleanly it
needs three capabilities upstream subgen doesn't ship:

- **`POST /batch`** — bulk scan with one `scan_id` wrapping N files, used by
  subarr's scan runner to submit prioritised gap lists in one round-trip.
- **`GET /queue`** — queue introspection (type-tracked, dedup-aware) used by
  subarr's header counter, completion watcher, and activity feed.
- **Per-language `SUBGEN_KWARGS_LANG_XX` env-var overrides** — applied in
  subgen's transcribe pipeline so each language can use its own
  faster-whisper kwargs.

Plus a handful of smaller fixes (eager model load on boot, reverse-sort in
`transcribe_existing`, structured response shapes).

This repo follows the **distro patch-stack** pattern: vanilla upstream subgen
is a git submodule pinned to a specific commit; our changes live as discrete
`.patch` files in `patches/`; a build script applies them and produces a
docker image we publish to GHCR.

## Quickstart

```yaml
# compose.yaml
services:
  subgen:
    image: ghcr.io/coaxk/subarr-subgen:2026.05.3-r1
    # ... rest is identical to upstream mccloud/subgen ...
```

That's it. Same env-vars as upstream, same volumes, same ports. Drop-in
replacement.

If you don't run subarr, you probably don't need this. Use upstream
`mccloud/subgen:latest` instead.

## Patches included

| # | Patch | What it adds |
|---|---|---|
| 0001 | `per-language-kwargs` | Reads `SUBGEN_KWARGS_LANG_<CODE>` env vars and merges into transcribe kwargs per detected language |
| 0002 | `eager-model-load` | Loads the Whisper model on container start (default upstream loads lazily on first request) |
| 0003 | `reverse-sort-transcribe-existing` | Adds `?reverse=true` to bulk scans so newest files transcribe first |
| 0004 | `batch-structured-response` | `/batch` returns `{scan_id, dispatched, skipped, errors}` JSON instead of plain text |
| 0005 | `gsq-return-str` | `gen_subtitles_queue` returns a string scan_id used by `/batch` |
| 0006 | `fastapi-jsonresponse-import` | Widens FastAPI import to include `JSONResponse` |
| 0007 | `deduplicated-queue-type-tracking-and-queue-endpoint` | `DeduplicatedQueue` tracks `(path, type)` instead of bare paths; adds `GET /queue` route |

See [`patches/`](./patches/) for the full diffs.

## Pinning + upgrades

Image tags follow `<upstream_version>-r<patch_rev>`:

- `2026.05.3-r1` — first build against upstream subgen 2026.05.3, patch revision 1
- `:latest` — newest release (any stability)
- `:stable` — manually promoted after ≥7 days in `:latest` without reported regression

Always pin to a specific `-r<N>` tag in production. See [`docs/tagging.md`](./docs/tagging.md).

## Reporting issues

- **Is the bug in subgen itself** (transcription quality, language detection, whisper model loading)? File at [McCloudS/subgen](https://github.com/McCloudS/subgen/issues).
- **Is the bug in one of our patches** (`/batch` shape wrong, `/queue` returning bad data, per-lang kwargs not being honoured)? File here.
- **Is the bug in how subarr drives subgen**? File at [coaxk/subarr](https://github.com/coaxk/subarr/issues).

If you're unsure, file here and we'll redirect.

## Building from source

```bash
git clone --recursive https://github.com/coaxk/subarr-subgen
cd subarr-subgen
./scripts/build.sh
```

Produces a local `subarr-subgen:dev` image.

## How the rebase-test works

Every Monday at 06:00 UTC a workflow fetches the latest upstream subgen from
`McCloudS/subgen` and tries to apply our patches against it. If everything
applies clean and smoke tests pass, we open a PR to bump the submodule pin.
If a patch fails to apply, a sticky GitHub issue is opened so we know
upstream restructured something we depend on. See [`docs/upstream-sync.md`](./docs/upstream-sync.md).

## License + attribution

This repo's tooling (build scripts, patches, CI workflows) is MIT licensed.

The upstream subgen code itself remains under its own license; see
[`NOTICE`](./NOTICE) for attribution. We don't redistribute upstream source
in this repo — only patches against it. The published docker image contains
upstream code + our patches as derived work, per upstream's license terms.
