# tests/test_capability_audit.py
from pathlib import Path

from scripts.capability_audit import (
    ADVERTISED_CAPABILITIES,
    Hunk,
    HunkOutcome,
    build_capability_map,
    capabilities_added_by_patch,
    classify_cumulative,
    classify_hunk,
    hunk_as_patch,
    hunks_of,
    patches_in_series_order,
    preserve_manual_section,
    render_report,
    seams_for_patch,
)

PATCHES_DIR = Path(__file__).resolve().parent.parent / "patches"

PATCH_WITH_CONTEXT = """--- a/subgen.py
+++ b/subgen.py
@@ -580,6 +580,7 @@ def queue_status():
             "capabilities": {
                 "audio_language_override": True,
+                "queue_cancel": True,
             },
"""


def test_only_added_lines_count():
    # audio_language_override is CONTEXT here, not provided by this patch.
    assert capabilities_added_by_patch(PATCH_WITH_CONTEXT) == {"queue_cancel"}


def test_patch_with_no_capabilities_returns_empty():
    assert capabilities_added_by_patch("--- a/x\n+++ b/x\n+print('hi')\n") == set()


def test_non_boolean_capability_values_still_count():
    # concurrent_transcriptions is an int, not True.
    body = '--- a/s\n+++ b/s\n+            "concurrent_transcriptions": concurrent_transcriptions,\n'
    assert capabilities_added_by_patch(body) == {"concurrent_transcriptions"}


def test_removal_lines_are_ignored():
    body = '--- a/s\n+++ b/s\n-                "old_flag": True,\n'
    assert capabilities_added_by_patch(body) == set()


def test_multiple_capabilities_on_one_line():
    # Regression test: patches/0029-async-config-switch.patch has an added line
    # with two keys -- "state" and "model" -- and a naive .search() only ever
    # returns the first, silently dropping the second.
    body = '--- a/s\n+++ b/s\n+    "ignore_forced_subtitles": True, "runtime_config": True,\n'
    assert capabilities_added_by_patch(body) == {
        "ignore_forced_subtitles",
        "runtime_config",
    }


def test_capabilities_accumulate_across_lines():
    # Every other test in this file produces a set of size <= 1, which does not
    # prove the set actually grows across multiple added lines.
    body = (
        "--- a/s\n+++ b/s\n"
        '+            "detect_language_track": True,\n'
        '+            "audio_language_override": True,\n'
    )
    assert capabilities_added_by_patch(body) == {
        "detect_language_track",
        "audio_language_override",
    }


def test_advertised_list_is_the_sixteen_live_flags():
    assert len(ADVERTISED_CAPABILITIES) == 16
    assert "per_request_kwargs" in ADVERTISED_CAPABILITIES
    assert "asr_arena" in ADVERTISED_CAPABILITIES
    assert "runtime_config" in ADVERTISED_CAPABILITIES
    # Response fields must NOT be treated as capabilities.
    assert "queued_count" not in ADVERTISED_CAPABILITIES
    assert "ok" not in ADVERTISED_CAPABILITIES


def test_map_drops_non_capability_keys():
    patches = {
        "0007-queue.patch": '+                "queued_count": len(q),\n',
        "0010-queue-cancel.patch": '+                "queue_cancel": True,\n',
    }
    m = build_capability_map(patches)
    assert m == {"queue_cancel": ["0010-queue-cancel.patch"]}


def test_map_records_every_provider_for_a_capability():
    # b.patch is listed first here on purpose: build_capability_map must sort
    # its own output, not merely preserve whatever order the caller passed in.
    patches = {
        "b.patch": '+                "runtime_config": True,\n',
        "a.patch": '+                "runtime_config": True,\n',
    }
    assert build_capability_map(patches)["runtime_config"] == ["a.patch", "b.patch"]


def test_every_advertised_capability_is_provided_by_a_real_patch():
    # Guards against DRIFT: if a future patch renames or drops one of the 16
    # literals, capabilities_added_by_patch stops finding it and
    # build_capability_map silently omits it -- indistinguishable downstream
    # from "never provided". This must fail loudly, not pass vacuously, so it
    # asserts the patch list is non-empty before the subset check.
    patch_files = sorted(PATCHES_DIR.glob("*.patch"))
    assert patch_files, f"no patch files found under {PATCHES_DIR}"

    provided: set[str] = set()
    for path in patch_files:
        provided |= capabilities_added_by_patch(
            path.read_text(encoding="utf-8", errors="replace")
        )

    missing = ADVERTISED_CAPABILITIES - provided
    assert not missing, (
        f"advertised capabilities with no patch provider: {sorted(missing)}"
    )


HUNKS = """--- a/subgen.py
+++ b/subgen.py
@@ -580,6 +580,7 @@ def queue_status():
+    x = 1
@@ -700,3 +701,4 @@ async def asr(
+    y = 2
@@ -900,1 +902,1 @@ class NewFileHandler(FileSystemEventHandler):
+    z = 3
"""


def test_extracts_function_names_from_hunk_headers():
    assert seams_for_patch(HUNKS) == {"queue_status", "asr", "NewFileHandler"}


def test_hunk_header_without_context_is_skipped():
    # A hunk at file top has no enclosing symbol; it is not a seam.
    assert seams_for_patch("@@ -1,4 +1,8 @@\n+x = 1\n") == set()


def test_annotated_def_signature_is_handled():
    # No decorator here on purpose -- a decorator can never appear in a hunk-
    # header context under git's default funcname heuristic ("@" is not in
    # [[:alpha:]$_], confirmed: 0 of 129 real headers match `@@ *@`). Do not
    # widen _SYMBOL to accept "@app.get(...)" and start harvesting route
    # paths as seams; there is nothing to widen it for.
    body = "@@ -1,2 +1,3 @@ def gen_subtitles_queue(file_path: str, t: str) -> None:\n+pass\n"
    assert seams_for_patch(body) == {"gen_subtitles_queue"}


def test_nested_diff_marker_on_a_patched_line_is_not_a_hunk_header():
    # A patch that ADDS or shows-as-context a line looking like a hunk header
    # must not contribute a seam -- only column-0 `@@` is a real header.
    body = (
        "@@ -1,2 +1,3 @@ def real_seam():\n"
        "+@@ -9,9 +9,9 @@ def added_phantom():\n"
        " @@ -8,8 +8,8 @@ def context_phantom():\n"
    )
    assert seams_for_patch(body) == {"real_seam"}


def test_single_line_hunk_header_without_counts():
    assert seams_for_patch("@@ -5 +5 @@ def path_mapping(fullpath):\n+x\n") == {
        "path_mapping"
    }


TWO_HUNKS = (
    "--- a/subgen.py\n"
    "+++ b/subgen.py\n"
    "@@ -10,2 +10,3 @@ def alpha():\n"
    "     keep\n"
    "-    drop\n"
    "+    add1\n"
    "+    add2\n"
    "@@ -50,2 +51,2 @@ def beta():\n"
    "     ctx\n"
    "-    old\n"
    "+    new\n"
)


def test_splits_into_one_hunk_per_header():
    hs = hunks_of("0001-x.patch", TWO_HUNKS)
    assert [h.header.strip() for h in hs] == [
        "@@ -10,2 +10,3 @@ def alpha():",
        "@@ -50,2 +51,2 @@ def beta():",
    ]
    assert all(h.patch == "0001-x.patch" for h in hs)
    assert all(h.file == "subgen.py" for h in hs)


def test_hunk_body_is_bounded_by_its_declared_counts():
    # The body must stop where the counts say, NOT at the next line that merely
    # looks like a header. A removed line can legitimately start with "--".
    body = hunks_of("p", TWO_HUNKS)[0].body
    assert body == "     keep\n-    drop\n+    add1\n+    add2\n"


def test_target_file_tracks_across_a_multi_file_patch():
    text = (
        "--- a/subgen.py\n"
        "+++ b/subgen.py\n"
        "@@ -1,1 +1,1 @@ def a():\n"
        "-x\n"
        "+y\n"
        "--- a/entrypoint.sh\n"
        "+++ b/entrypoint.sh\n"
        "@@ -1,1 +1,1 @@\n"
        "-echo old\n"
        "+echo new\n"
    )
    assert [h.file for h in hunks_of("p", text)] == ["subgen.py", "entrypoint.sh"]


def test_countless_hunk_header_defaults_to_one_line_each_side():
    hs = hunks_of("p", "--- a/s.py\n+++ b/s.py\n@@ -5 +5 @@ def f():\n-a\n+b\n")
    assert len(hs) == 1
    assert hs[0].body == "-a\n+b\n"


def test_hunk_as_patch_reconstructs_something_git_can_apply():
    h = hunks_of("p", TWO_HUNKS)[1]
    out = hunk_as_patch(h)
    assert out.startswith("--- a/subgen.py\n+++ b/subgen.py\n@@ -50,2 +51,2 @@")
    assert out.endswith("     ctx\n-    old\n+    new\n")


def test_hunk_is_hashable_and_carries_its_provenance():
    h = hunks_of("0016-asr.patch", TWO_HUNKS)[0]
    assert isinstance(h, Hunk)
    assert {h}  # must be usable in a set
    assert h.patch == "0016-asr.patch"


def test_hunk_with_overrunning_counts_stops_at_the_next_header():
    # A hand-edited or fuzzy patch can declare more lines than it supplies.
    # Without a backstop the unresolved counts walk through the next hunk's
    # header and swallow it, losing that hunk entirely.
    text = (
        "--- a/s.py\n"
        "+++ b/s.py\n"
        "@@ -10,9 +10,9 @@ def alpha():\n"
        " ctx\n"
        "@@ -50,1 +50,1 @@ def beta():\n"
        "-old\n"
        "+new\n"
    )
    hs = hunks_of("p", text)
    assert len(hs) == 2
    assert hs[0].body == " ctx\n"
    assert hs[1].body == "-old\n+new\n"


def test_hunk_applying_to_both_is_intact():
    assert classify_hunk(True, True) is HunkOutcome.INTACT


def test_hunk_applying_to_base_but_not_branch_is_broken():
    assert classify_hunk(True, False) is HunkOutcome.BROKEN_BY_BRANCH


def test_hunk_failing_on_base_is_inconclusive_whatever_the_branch_says():
    # Failing on base means the probe cannot see this hunk standalone -- it
    # depends on earlier patches in the stack. That is not evidence of breakage
    # in EITHER direction, so both branch results collapse to INCONCLUSIVE.
    assert classify_hunk(False, False) is HunkOutcome.INCONCLUSIVE
    assert classify_hunk(False, True) is HunkOutcome.INCONCLUSIVE


# ---------------------------------------------------------------------------
# The cross-tabulation. classify_hunk above reads ONE probe; these read both.
# ---------------------------------------------------------------------------


def test_cumulative_base_failure_is_a_base_anomaly():
    # The stack applies to the pinned base 129/129 in series order, so a
    # cumulative-base failure means the TOOL is broken, not the branch. It
    # therefore outranks every other signal in the row, including a
    # decisive-looking standalone break: once the base pass has failed, nothing
    # else in that row is trustworthy enough to report as a finding.
    assert classify_cumulative(True, True, False, True) is HunkOutcome.BASE_ANOMALY
    assert classify_cumulative(True, False, False, True) is HunkOutcome.BASE_ANOMALY
    assert classify_cumulative(False, False, False, False) is HunkOutcome.BASE_ANOMALY


def test_standalone_break_is_decisive_whatever_the_cumulative_probe_says():
    # Applies standalone to the pinned base and not to the branch => the branch
    # removed upstream text this hunk lands on. Ordering cannot explain that
    # away, so it stays BROKEN_BY_BRANCH even if the cumulative branch pass
    # happens to accept it at an offset.
    assert classify_cumulative(True, False, True, False) is HunkOutcome.BROKEN_BY_BRANCH
    assert classify_cumulative(True, False, True, True) is HunkOutcome.BROKEN_BY_BRANCH


def test_cumulative_branch_success_is_intact():
    assert classify_cumulative(True, True, True, True) is HunkOutcome.INTACT
    # The resolution that matters: standalone could not judge this hunk at all,
    # because its anchor is text an EARLIER patch of ours creates and a
    # pristine tree never has it. The cumulative pass supplies that anchor and
    # the hunk still lands on the branch.
    assert classify_cumulative(False, False, True, True) is HunkOutcome.INTACT
    assert classify_cumulative(False, True, True, True) is HunkOutcome.INTACT


def test_hunk_an_earlier_break_took_is_cascade():
    # No standalone verdict, and cumulatively it does not land on the branch:
    # the anchor it needed was one of OUR added lines, and the hunk that adds
    # it failed earlier in the series. Attributable to that break, not
    # independent evidence of damage.
    assert classify_cumulative(False, False, True, False) is HunkOutcome.CASCADE
    assert classify_cumulative(False, True, True, False) is HunkOutcome.CASCADE
    # Even a hunk that applies standalone to BOTH trees cascades when an
    # earlier break has already moved the ground under it.
    assert classify_cumulative(True, True, True, False) is HunkOutcome.CASCADE


def test_cumulative_outcomes_are_their_own_members():
    # StrEnum members compare equal to their value, so a typo'd alias would
    # pass an `is` check against the wrong member without this.
    assert HunkOutcome.CASCADE.value == "CASCADE"
    assert HunkOutcome.BASE_ANOMALY.value == "BASE_ANOMALY"
    assert len({HunkOutcome.CASCADE, HunkOutcome.BASE_ANOMALY, HunkOutcome.INTACT}) == 3


SERIES_TEXT = """# Patch application order -- quilt-style.
#
# Smallest, most-isolated patch first.

0001-a.patch
0002-b.patch

  0003-c.patch
"""


def test_series_order_skips_comments_and_blank_lines():
    assert patches_in_series_order(SERIES_TEXT) == [
        "0001-a.patch",
        "0002-b.patch",
        "0003-c.patch",
    ]


def test_series_order_is_file_order_not_sorted_order():
    # The cumulative probe mutates one tree in this order, so the order IS the
    # semantics. Sorting it would be a different experiment.
    assert patches_in_series_order("0009-b.patch\n0001-a.patch\n") == [
        "0009-b.patch",
        "0001-a.patch",
    ]


def test_series_lists_exactly_the_patch_files_on_disk():
    # A patch file missing from `series` is never applied to the cumulative
    # tree, so every later hunk that needs its added lines fails and is scored
    # CASCADE -- damage manufactured by a bookkeeping slip. A series entry with
    # no file on disk is the same slip in the other direction. Both directions
    # must fail loudly.
    on_disk = {p.name for p in PATCHES_DIR.glob("*.patch")}
    assert on_disk, f"no patch files found under {PATCHES_DIR}"
    listed = set(
        patches_in_series_order((PATCHES_DIR / "series").read_text(encoding="utf-8"))
    )
    assert listed == on_disk


def test_report_names_broken_hunks_and_carries_the_sha():
    rows = [
        (
            "asr_arena",
            ["0016.patch"],
            {HunkOutcome.BROKEN_BY_BRANCH: 2, HunkOutcome.CASCADE: 3},
            ["@@ -1,2 +1,2 @@ def asr_task_worker(task_data: dict) -> None:"],
        ),
        ("queue_cancel", ["0010.patch"], {HunkOutcome.INTACT: 1}, []),
    ]
    out = render_report(rows, branch_sha="7997624")
    assert "asr_arena" in out and "queue_cancel" in out
    assert "7997624" in out
    assert "asr_task_worker" in out  # the specific broken hunk must be named


def test_report_names_broken_hunks_no_capability_row_can_reach():
    # 7 of the 11 real breaks live in patches that add no capability literal,
    # so build_capability_map gives them no row and the per-capability section
    # cannot name them -- including the args.update(kwargs) triple, the most
    # load-bearing break in the stack. Without a stack-wide list the report
    # hides its own best evidence, which is caveat 2 biting the report itself.
    orphan = Hunk(
        "0001-per-language-kwargs.patch",
        "subgen.py",
        "@@ -1595,6 +1628,16 @@ def gen_subtitles(file_path: str) -> None:\n",
        "+    args.update(kwargs)\n",
    )
    out = render_report([], branch_sha="deadbee", broken=[orphan])
    assert "gen_subtitles" in out
    assert "0001-per-language-kwargs.patch" in out


def test_report_always_carries_the_custom_regroup_row():
    # CUSTOM_REGROUP advertises no flag, so nothing derives it -- yet it is the
    # one genuine seam loss. A report that can omit it is worthless.
    out = render_report([], branch_sha="deadbee")
    assert "CUSTOM_REGROUP" in out
    assert "GONE" in out


def test_report_describes_both_probes_and_shows_both_columns():
    # The cross-tabulation is the point, so a report that shows only the
    # resolved column hides how the resolution was reached -- and one that
    # shows only the standalone column is the old lower-bound report.
    out = render_report(
        [],
        branch_sha="deadbee",
        per_patch={"0001-x.patch": {HunkOutcome.INCONCLUSIVE: 2}},
        resolved_per_patch={"0001-x.patch": {HunkOutcome.CASCADE: 2}},
    )
    assert "standalone" in out.lower()
    assert "cumulative" in out.lower()
    assert "series" in out.lower()  # the order the cumulative probe applies in
    assert "INCONCLUSIVE 2" in out
    assert "CASCADE 2" in out


def test_report_states_the_census_is_complete_and_never_calls_it_a_lower_bound():
    # This replaces an assertion that the report DOES call its own numbers a
    # lower bound. That caveat was true of the standalone probe alone; the
    # cumulative probe resolves all 86 INCONCLUSIVE hunks, so repeating it now
    # understates a complete result. The absence check is the load-bearing
    # half: it fails if the stale wording is ever reinstated.
    out = render_report([], branch_sha="deadbee")
    assert "lower bound" not in out.lower()
    assert "complete" in out.lower()
    assert "CASCADE" in out
    assert "attributable" in out.lower()


def test_report_states_the_base_anomaly_invariant_even_at_zero():
    # BASE_ANOMALY 0 is what makes every other number in the report readable,
    # and _counts_cell drops zero counts -- so it can never come from the
    # tally and has to be stated outright.
    out = render_report(
        [],
        branch_sha="deadbee",
        resolved_per_patch={"0001-x.patch": {HunkOutcome.INTACT: 3}},
    )
    assert "BASE_ANOMALY" in out
    assert "3/3" in out


def test_preserve_manual_section_returns_the_hand_written_tail():
    existing = "# report\n\nmachine stuff\n\n## Manual pass\n\n### `x` - GONE\n"
    assert preserve_manual_section(existing) == "## Manual pass\n\n### `x` - GONE\n"


def test_preserve_manual_section_is_empty_when_there_is_none():
    assert preserve_manual_section("# report\n\nmachine stuff only\n") == ""


def test_preserve_manual_section_survives_a_round_trip():
    # Regeneration must be idempotent: the preserved tail has to itself be
    # preservable, or the SECOND re-run silently loses what the first kept.
    existing = "# old machine output\n## Manual pass\n\nanalysis\n"
    kept = preserve_manual_section(existing)
    assert preserve_manual_section("# new machine output\n" + kept) == kept
