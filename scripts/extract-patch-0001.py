#!/usr/bin/env python3
"""One-shot helper to apply ONLY patch 0001's transformations (per-language
kwargs) to upstream/subgen.py.

After running this:
    cd upstream
    git diff subgen.py            # inspect what got changed
    git commit -am "0001: per-language kwargs"
    git format-patch -1 --no-signature --zero-commit -o ../patches/

We DO NOT keep this script around long-term — once all 7 patches are
extracted and validated, the .patch files are the source of truth and
this helper is a one-time bootstrap artefact. Kept under scripts/ for
audit purposes (reproducibility of the original extraction).

Mirrors the logic in:
  C:\\DockerContainers\\scripts\\subgenpyupdatemerge\\update_subgen_v4.py
  steps 4 only.
"""

import sys
from pathlib import Path

T_KWARGS_ANCHOR = (
    "    logging.info(\"kwargs (SUBGEN_KWARGS) is an invalid "
    "dictionary, defaulting to empty '{}'\")"
)

PERLANG_BLOCK = """
# [v4 PATCH] PER-LANGUAGE KWARGS  (reads SUBGEN_KWARGS_LANG_<CODE>)
# Wired into args at each transcribe site below (not dead code).
language_specific_kwargs = {}
for _env_k, _env_v in os.environ.items():
    if _env_k.startswith('SUBGEN_KWARGS_LANG_'):
        _lc = _env_k.replace('SUBGEN_KWARGS_LANG_', '').lower()
        try:
            language_specific_kwargs[_lc] = ast.literal_eval(_env_v)
            logging.info(f"Loaded per-language kwargs for {_lc}: {language_specific_kwargs[_lc]}")
        except Exception as _e:
            logging.error(f"Failed to parse SUBGEN_KWARGS_LANG_{_lc.upper()}: {_e}")
"""

WIRE_OLD = "        args.update(kwargs)\n"
WIRE_NEW = (
    "        args.update(kwargs)\n"
    "        try:\n"
    "            _lc = None\n"
    "            if 'force_language' in dir() and force_language is not None:\n"
    "                _lc = force_language.to_iso_639_1()\n"
    "            elif 'language' in dir() and language:\n"
    "                _lc = str(language).lower()\n"
    "            if _lc and language_specific_kwargs.get(_lc):\n"
    "                args.update(language_specific_kwargs[_lc])\n"
    "        except Exception:\n"
    "            pass\n"
)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    target = repo_root / "upstream" / "subgen.py"
    if not target.is_file():
        print(f"error: {target} not found", file=sys.stderr)
        return 2

    code = target.read_text(encoding="utf-8")

    # Sanity gates — fail closed if the anchors aren't where we expect.
    if T_KWARGS_ANCHOR not in code:
        print("error: T_KWARGS_ANCHOR not found in upstream — refusing to patch", file=sys.stderr)
        return 3
    if "language_specific_kwargs = {}" in code:
        print("error: patch already applied — refusing to double-apply", file=sys.stderr)
        return 4
    wire_count = code.count(WIRE_OLD)
    if wire_count == 0:
        print("error: WIRE_OLD pattern not found — args.update(kwargs) sites missing", file=sys.stderr)
        return 5

    # Apply.
    code = code.replace(T_KWARGS_ANCHOR, T_KWARGS_ANCHOR + "\n" + PERLANG_BLOCK, 1)
    code = code.replace(WIRE_OLD, WIRE_NEW)

    target.write_text(code, encoding="utf-8", newline="\n")

    print(f"  block inserted: 1 site (after SUBGEN_KWARGS anchor)")
    print(f"  wiring inserted: {wire_count} sites (args.update(kwargs) calls)")
    print(f"  written to: {target}")
    print()
    print("next:")
    print("  cd upstream && git diff subgen.py        # inspect")
    print("  cd upstream && git commit -am '0001: per-language kwargs (SUBGEN_KWARGS_LANG_<CODE>)'")
    print("  cd upstream && git format-patch -1 --no-signature --zero-commit -o ../patches/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
