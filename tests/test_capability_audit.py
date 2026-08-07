# tests/test_capability_audit.py
from pathlib import Path

from scripts.capability_audit import (
    ADVERTISED_CAPABILITIES,
    Hunk,
    build_capability_map,
    capabilities_added_by_patch,
    hunk_as_patch,
    hunks_of,
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
