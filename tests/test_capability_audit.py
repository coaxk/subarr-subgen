# tests/test_capability_audit.py
from scripts.capability_audit import capabilities_added_by_patch

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
