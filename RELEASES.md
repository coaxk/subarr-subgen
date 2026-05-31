# subarr-subgen releases

Patch-rev provenance for the `subarr-subgen` quilt stack. Each row
captures one shipped revision against a known-good upstream subgen
commit. Yank a row when a real-world install hits a regression we
can't hotfix in-place — the `status` column drops to `yanked` and the
`yank_reason` explains why.

This file is the canonical "is patch v4.x safe to apply?" reference.
subarr's update checker reads it via the GitHub API on every health
probe; a `yanked` rev triggers a warning chip in Settings → Updates.

## Format

Add a new row at the top of the table for every shipped patch rev.
Format: pipe-separated markdown. Dates are ISO; status values are
`healthy`, `superseded`, or `yanked`.

| Rev    | Status     | Date       | Upstream sha | Notes |
|--------|------------|------------|--------------|-------|
| v4.3   | healthy    | 2026-05-31 | b4fbc8d      | Adds `audio_language_override` query param on POST /batch + capability advertisement (`subarr_subgen_patch_rev`, `capabilities.audio_language_override`) on GET /queue. Lets subarr verified-audio rows bypass `SKIP_IF_AUDIO_LANGUAGES=eng` without disabling the skip-list globally. |
| v4.2   | superseded | 2026-05-28 | b4fbc8d      | Added GET /queue endpoint (dict-keyed `DeduplicatedQueue`). Foundation for subarr's queue monitor. |
| v4.1   | superseded | 2026-05-27 | 69ecaca      | POST /batch structured response: `{walked, queued, skipped, already_in_queue, no_audio, pending_language_detect}` instead of bare text. Lets subarr scan_runner classify path outcomes. |
| v4.0   | superseded | 2026-05-26 | 69ecaca      | Per-language `SUBGEN_KWARGS_LANG_<CODE>` block resolution. Auto-picks the right block based on detected/forced audio language. |

## Procedure: yank a rev

1. Confirm the failure mode is REAL — got a stack trace + repro from a
   user OR our own staging install with the patched build.
2. Update this file: change the row's status to `yanked`, append
   `yank_reason` after the existing Notes content. Push to main.
3. If the regression is fixable forward, ship the fix as a new rev
   (e.g. v4.3 yanked → v4.4 healthy). subarr's UI will surface "patch
   v4.3 yanked — upgrade to v4.4" without manual intervention from the
   user.
4. If not fixable forward in a sane time, edit the apply-patches.sh
   `default rev` constant down to the last healthy rev so fresh
   `subarr-subgen` clones don't apply the yanked patch.

## Procedure: superseding a rev

Just append the new row at the top with status `healthy` and flip the
previous rev's status to `superseded`. Superseded ≠ broken; older
deployments that haven't upgraded yet keep working. Yank a superseded
rev only if you discover a bug AFTER it's no longer current — same
yank procedure applies.

## subarr's update checker

`/api/updates/state` in subarr reads the latest `healthy` rev from
this file and compares against the running subgen's `subarr_subgen_patch_rev`
field (advertised via GET /queue). When the user's rev is older, the
update banner offers the upgrade with a one-click compose-edit
walkthrough. When the user's rev is `yanked`, the banner switches to a
red warning with the `yank_reason` text.
