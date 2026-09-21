"""Runtime smoke for patch 0054: a direct task can never be claimed while the
model is being unloaded (subarr-subgen#69).

Run INSIDE the built image (the patched tree needs torch, faster_whisper, av...):

    docker run --rm -v "$PWD/upstream:/work:ro" -v "$PWD/tests:/smoke:ro" \
      -w /work -e PYTHONPATH=/work --entrypoint python3 \
      ghcr.io/coaxk/subarr-subgen:<tag> /smoke/smoke_direct_task_race.py

WHY THIS EXISTS. perform_model_cleanup() reads "is the system idle" and then
unloads the model, holding `model_cleanup_lock` across both. Before 0054 a
direct request only incremented `active_direct_tasks`, which is read during
that check — so a request arriving AFTER the read but BEFORE the unload was
counted by nobody and ran against a model being torn down. Live on 2026-09-19:

    14.057  Executing scheduled model cleanup
    14.057  Queue and direct tasks idle; clearing model from memory.
    14.126  Immediate language detection (Queue Bypass) for <file>
    14.145  Model unloaded from memory
    14.398  Error in API detect-language: No model replica is available

The window is ~90 ms in production, so a test that merely races two threads
would pass on a good day whatever the code did. These tests WIDEN the window
deliberately (the unload blocks on an event) so the ordering is decided by the
locking and not by timing.
"""

import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.environ.get("SUBGEN_TREE", "/work"))

import subgen  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(
        f"{'PASS' if cond else '*** FAIL ***'}  {name}{('  -> ' + detail) if detail else ''}"
    )
    if not cond:
        FAILS.append(name)


class _FakeInner:
    def __init__(self, events, gate=None):
        self._events = events
        self._gate = gate

    def unload_model(self):
        self._events.append("unload_start")
        if self._gate is not None:
            self._gate.wait(5)
        self._events.append("unload_end")


class _FakeModel:
    def __init__(self, events, gate=None):
        self.model = _FakeInner(events, gate)


class _IdleQueue:
    def __init__(self, idle=True):
        self._idle = idle

    def is_idle(self):
        return self._idle

    def get(self, block=True, timeout=None):
        # subgen starts transcription workers on import and they poll this.
        # Without a get() they log a traceback every second and bury the
        # check output; Empty is what a real idle queue raises.
        raise queue.Empty


def _reset(events, gate=None, idle=True):
    subgen.model = _FakeModel(events, gate)
    subgen.task_queue = _IdleQueue(idle)
    subgen.clear_vram_on_complete = True
    subgen.active_direct_tasks = 0
    subgen.model_cleanup_timer = None


# ── 1. a held claim stops the cleanup unloading at all ────────────────

events = []
_reset(events)
with subgen.direct_task_claim():
    subgen.perform_model_cleanup()
check(
    "a held claim keeps the model loaded",
    subgen.model is not None and "unload_start" not in events,
    f"events={events}",
)

# ── 2. with no claim, the cleanup does unload (the test above is not
#      passing merely because cleanup never runs) ─────────────────────

events = []
_reset(events)
subgen.perform_model_cleanup()
check(
    "with nothing claimed, the cleanup still unloads",
    subgen.model is None and events == ["unload_start", "unload_end"],
    f"model={subgen.model} events={events}",
)

# ── 3. the race itself: a claim may never land mid-unload ─────────────

events = []
gate = threading.Event()
_reset(events, gate)

cleaner = threading.Thread(target=subgen.perform_model_cleanup, daemon=True)
cleaner.start()
# wait until the unload has genuinely started, so the claim below is racing
# the real window rather than an empty one
for _ in range(500):
    if "unload_start" in events:
        break
    time.sleep(0.01)
started = "unload_start" in events


def _claim():
    with subgen.direct_task_claim():
        events.append("claim")


claimer = threading.Thread(target=_claim, daemon=True)
claimer.start()
time.sleep(0.2)  # give a broken build every chance to claim mid-unload
gate.set()  # let the unload finish
claimer.join(5)
cleaner.join(5)

mid_unload = (
    "claim" in events
    and events.index("claim") > events.index("unload_start")
    and events.index("claim") < events.index("unload_end")
)
check("the unload window really opened", started, f"events={events}")
check("no claim is granted mid-unload", not mid_unload, f"events={events}")
check(
    "the claim is granted once the unload finishes",
    "claim" in events,
    f"events={events}",
)

# ── 4. the counter still gates the cleanup after a claim is released ──

events = []
_reset(events)
with subgen.direct_task_claim():
    pass
subgen.perform_model_cleanup()
check(
    "a released claim no longer holds the model",
    subgen.model is None,
    f"events={events}",
)

# ── 5. lock ordering: claim and cleanup take both locks the same way,
#      which is what keeps this deadlock-free. Hammer it. ─────────────

events = []
_reset(events, idle=False)  # not idle: cleanup skips, both still lock
stop = time.time() + 2
errors = []


def _hammer_claim():
    try:
        while time.time() < stop:
            with subgen.direct_task_claim():
                pass
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))


def _hammer_cleanup():
    try:
        while time.time() < stop:
            subgen.perform_model_cleanup()
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))


threads = [threading.Thread(target=_hammer_claim, daemon=True) for _ in range(4)]
threads += [threading.Thread(target=_hammer_cleanup, daemon=True) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join(10)
check(
    "claim and cleanup do not deadlock under contention",
    all(not t.is_alive() for t in threads) and not errors,
    f"alive={[t.is_alive() for t in threads]} errors={errors}",
)
check(
    "the counter is balanced after the hammer",
    subgen.active_direct_tasks == 0,
    f"active_direct_tasks={subgen.active_direct_tasks}",
)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
    sys.exit(1)
print("all direct-task race checks passed")
