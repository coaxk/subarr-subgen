#!/usr/bin/env python3
"""Validate that the patched upstream/subgen.py meets subarr's structural
contract. Runs after apply-patches.sh.

Gates (in order):
  1. compile() — patched source must compile in-memory without SyntaxError
  2. AST: transcribe_existing has 'reverse' arg
  3. AST: batch() has 'reverse' arg
  4. AST: gen_subtitles_queue returns at least one string constant
  5. text: language_specific_kwargs present (from patch 0001)
  6. text: '@app.get("/queue")' present (from patch 0007)
  7. text: 'JSONResponse' imported (from patch 0006)
  8. text: '[v4.2 PATCH] _queued / _processing track' present (from patch 0007)
  9. text: 'Eager model load on boot' present (from patch 0002)

Exits non-zero with a clear message on first failure. This is the
"would subarr-subgen actually work?" gate; a clean run means the image
is safe to build.

Mirrors update_subgen_v4.py's STEP 7 (compile) and STEP 8 (AST) gates.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "upstream" / "subgen.py"


def fail(msg: str) -> None:
    print(f"VALIDATE: FAIL — {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"VALIDATE: ok — {msg}")


def fn_args(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return [a.arg for a in n.args.args]
    return None


def fn_returns_string_constant(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            for sub in ast.walk(n):
                if (
                    isinstance(sub, ast.Return)
                    and isinstance(sub.value, ast.Constant)
                    and isinstance(sub.value.value, str)
                ):
                    return True
    return False


def main() -> int:
    if not TARGET.is_file():
        fail(f"{TARGET} not found — did you run apply-patches.sh?")
    code = TARGET.read_text(encoding="utf-8")

    # Gate 1: compile
    try:
        compile(code, str(TARGET), "exec")
    except SyntaxError as e:
        fail(f"compile() failed: {e}")
    ok("compile() passed")

    tree = ast.parse(code)

    # Gate 2-4: function signatures + returns
    te_args = fn_args(tree, "transcribe_existing")
    if not te_args or "reverse" not in te_args:
        fail(f"transcribe_existing missing 'reverse' arg (got {te_args})")
    ok(f"transcribe_existing{tuple(te_args)} has reverse")

    ba_args = fn_args(tree, "batch")
    if not ba_args or "reverse" not in ba_args:
        fail(f"batch() missing 'reverse' arg (got {ba_args})")
    ok(f"batch{tuple(ba_args)} has reverse")

    # Gate: patch 0024 (per-request ignore_forced threading)
    if "ignore_forced" not in (ba_args or []):
        fail(
            f"batch() missing 'ignore_forced' arg (got {ba_args}) — patch 0024 not landed"
        )
    ok("batch() has ignore_forced (patch 0024)")

    ssf_args = fn_args(tree, "should_skip_file")
    if not ssf_args or "ignore_forced_override" not in ssf_args:
        fail(
            f"should_skip_file missing 'ignore_forced_override' (got {ssf_args}) — patch 0024"
        )
    ok("should_skip_file has ignore_forced_override (patch 0024)")

    hisl_args = fn_args(tree, "has_internal_subtitle_in_language")
    if not hisl_args or "ignore_forced_override" not in hisl_args:
        fail(
            f"has_internal_subtitle_in_language missing 'ignore_forced_override' (got {hisl_args}) — patch 0024"
        )
    ok("has_internal_subtitle_in_language has ignore_forced_override (patch 0024)")

    if not fn_returns_string_constant(tree, "gen_subtitles_queue"):
        fail(
            "gen_subtitles_queue has no string-constant return — patch 0005 not landed"
        )
    ok("gen_subtitles_queue returns dispatch strings")

    # Gate 5-9: text presence
    text_checks = [
        ("language_specific_kwargs", "patch 0001 (per-lang kwargs)"),
        ("Eager model load on boot", "patch 0002 (eager-load)"),
        ("[v4.2 PATCH] _queued / _processing track", "patch 0007 (DQ type-tracking)"),
        ('@app.get("/queue")', "patch 0007 (/queue endpoint)"),
        (
            "from fastapi.responses import StreamingResponse, JSONResponse",
            "patch 0006 (JSONResponse import)",
        ),
        ("[v4.1 PATCH] Structured dispatch counts", "patch 0003 (structured counts)"),
        ("return JSONResponse(content=result", "patch 0004 (/batch JSONResponse)"),
        ('@app.post("/config")', "patch 0022 (/config endpoint)"),
        ('"runtime_config": True', "patch 0022 (runtime_config capability)"),
        ("subarr_subgen_release_tag", "patch 0022 (release tag emission)"),
        (
            '"concurrent_transcriptions": concurrent_transcriptions',
            "patch 0023 (concurrent_transcriptions capability)",
        ),
        (
            '"request_ignore_forced": True',
            "patch 0024 (request_ignore_forced capability)",
        ),
        ("_eff_ignore_forced", "patch 0024 (per-request forced override logic)"),
        ("def path_is_allowed", "patch 0025 (#13 containment helper)"),
        ("SUBGEN_PATH_ALLOWLIST", "patch 0025 (#13 containment allowlist env)"),
        ("if not path_is_allowed(audio_path):", "patch 0025 (#13 /asr containment)"),
        (
            "if not path_is_allowed(path_mapping(directory)):",
            "patch 0025 (#13 /batch containment)",
        ),
        ("if not path_is_allowed(mapped):", "patch 0025 (#13 /detect containment)"),
    ]
    for needle, label in text_checks:
        if needle not in code:
            fail(f"text: missing — {label} (needle: {needle!r})")
        ok(label)

    print()
    print("VALIDATE: all gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
