"""Runtime smokes for our patched transcribe_existing / SKIP_STARTUP_SCAN behaviour.

Run INSIDE the built image (the patched tree needs torch, faster_whisper, av...):

    docker run --rm -v "$PWD/upstream:/work:ro" -v "$PWD/tests:/smoke:ro"       -w /work -e PYTHONPATH=/work --entrypoint python3       ghcr.io/coaxk/subarr-subgen:<tag> /smoke/smoke_patched_behaviour.py

WHY THIS EXISTS: upstream ships tests for the .subgen_skip marker and
SKIP_STARTUP_SCAN, but it stubs gen_subtitles_queue with a lambda that does not
accept our patch-added kwargs (audio_language_override, ignore_forced_override),
so those tests die on TypeError before reaching their assertions. The doubles
here accept **kwargs, so they actually exercise the behaviour.

The last check is the important one: it pins patch 0033. Upstream gates
SKIP_STARTUP_SCAN inside transcribe_existing(), which /batch also calls, so
upstream semantics would silently no-op every transcription subarr requests.
If a future port drops 0033, that check fails.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SUBGEN_TREE", "/work"))

import subgen  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else '*** FAIL ***'}  {name}{('  -> ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)

def _tree():
    """root/a.mkv, root/b.mkv, root/keep/c.mkv, root/skipme/.subgen_skip + d.mkv"""
    root = tempfile.mkdtemp()
    for rel in ("a.mkv", "b.mkv"):
        open(os.path.join(root, rel), "w").close()
    os.makedirs(os.path.join(root, "keep"))
    open(os.path.join(root, "keep", "c.mkv"), "w").close()
    os.makedirs(os.path.join(root, "skipme"))
    open(os.path.join(root, "skipme", ".subgen_skip"), "w").close()
    open(os.path.join(root, "skipme", "d.mkv"), "w").close()
    return root


def run(root, **overrides):
    """Call transcribe_existing with a kwargs-tolerant queue double."""
    seen = []

    def fake_gsq(path, *a, **kw):
        seen.append(path)
        return "queued"

    orig_gsq = subgen.gen_subtitles_queue
    orig_monitor = subgen.monitor
    orig_pm = subgen.path_mapping
    subgen.gen_subtitles_queue = fake_gsq
    subgen.monitor = False
    subgen.path_mapping = lambda p: p
    try:
        counts = subgen.transcribe_existing(root, **overrides)
    finally:
        subgen.gen_subtitles_queue = orig_gsq
        subgen.monitor = orig_monitor
        subgen.path_mapping = orig_pm
    return seen, counts


root = _tree()

# --- 1. upstream's .subgen_skip marker still prunes (carried over verbatim) ---
seen, counts = run(root)
names = sorted(os.path.basename(p) for p in seen)
check("marker prunes the marked subtree", "d.mkv" not in names, f"walked={names}")
check(
    "unmarked files still walked",
    names == ["a.mkv", "b.mkv", "c.mkv"],
    f"walked={names}",
)

# --- 2. our reverse-sort still works ---
fwd, _ = run(root)
rev, _ = run(root, reverse=True)
check(
    "reverse=True inverts order",
    rev == list(reversed(fwd)),
    f"fwd[0]={os.path.basename(fwd[0])} rev[0]={os.path.basename(rev[0])}",
)

# --- 3. our structured counts still returned ---
check("counts dict returned", isinstance(counts, dict), f"type={type(counts).__name__}")
check(
    "counts.walked matches files queued",
    counts.get("walked") == len(seen),
    f"walked={counts.get('walked')} seen={len(seen)}",
)
check(
    "counts.queued tallied",
    counts.get("queued") == len(seen),
    f"queued={counts.get('queued')}",
)
check(
    "counts echoes reverse flag",
    counts.get("reverse") is False,
    f"reverse={counts.get('reverse')}",
)

# --- 4. THE DIVERGENCE: SKIP_STARTUP_SCAN must NOT gag an explicit call ---
orig_flag = subgen.skip_startup_scan
subgen.skip_startup_scan = True
try:
    seen_skip, counts_skip = run(root)
finally:
    subgen.skip_startup_scan = orig_flag
check(
    "SKIP_STARTUP_SCAN=1 does NOT no-op an explicit /batch-style call",
    len(seen_skip) == 3 and counts_skip.get("walked") == 3,
    f"walked={counts_skip.get('walked')} (upstream semantics would give 0)",
)


def boot(skip_flag):
    """Run lifespan startup with a fake Thread and report whether a scan spawned."""
    spawned = []

    class FakeThread:
        def __init__(self, *a, **kw):
            spawned.append(kw.get("target", a[0] if a else None))

        def start(self):
            pass

        def join(self, *a, **kw):
            pass

    orig_thread = subgen.threading.Thread
    orig_flag = subgen.skip_startup_scan
    orig_folders = subgen.transcribe_folders
    subgen.threading.Thread = FakeThread
    subgen.skip_startup_scan = skip_flag
    subgen.transcribe_folders = "/tmp"

    async def drive():
        async with subgen.lifespan(None):
            pass

    try:
        asyncio.run(drive())
    finally:
        subgen.threading.Thread = orig_thread
        subgen.skip_startup_scan = orig_flag
        subgen.transcribe_folders = orig_folders
    return spawned


off = boot(False)
check(
    "SKIP_STARTUP_SCAN unset -> boot scan thread IS started",
    len(off) == 1 and getattr(off[0], "__name__", "") == "transcribe_existing",
    f"spawned={[getattr(t, '__name__', t) for t in off]}",
)

on = boot(True)
check(
    "SKIP_STARTUP_SCAN=1 -> boot scan thread is NOT started",
    len(on) == 0,
    f"spawned={[getattr(t, '__name__', t) for t in on]}",
)


print()
print("RESULT:", "ALL SMOKES PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
