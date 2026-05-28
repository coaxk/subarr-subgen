#!/usr/bin/env python3
"""Bootstrap: extract patches 0002-0007 from update_subgen_v4.py + vanilla.

Same one-time-bootstrap pattern as extract-patch-0001.py. After this runs
once and produces the .patch files, the .patch files are the source of
truth and this script is just historical.

For each patch in order:
  1. Apply its textual transformation to upstream/subgen.py
  2. git -C upstream add + commit with the patch's canonical message
After all are applied:
  3. git format-patch -N --no-signature --zero-commit -o ../patches/
  4. Rename to canonical filenames
  5. Reset upstream to HEAD (back to vanilla pin)

Mirrors steps 5-6f of:
  C:\\DockerContainers\\scripts\\subgenpyupdatemerge\\update_subgen_v4.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "upstream"
PATCHES = REPO / "patches"


def run(cmd, **kw):
    """Run a command, raise on failure, return stdout."""
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(f"command failed: {cmd}", file=sys.stderr)
        print(f"stdout: {r.stdout}", file=sys.stderr)
        print(f"stderr: {r.stderr}", file=sys.stderr)
        raise SystemExit(2)
    return r.stdout


def read() -> str:
    return (UPSTREAM / "subgen.py").read_text(encoding="utf-8")


def write(code: str) -> None:
    (UPSTREAM / "subgen.py").write_text(code, encoding="utf-8", newline="\n")


def commit(msg: str) -> None:
    run(["git", "-C", str(UPSTREAM), "add", "subgen.py"])
    run(["git", "-C", str(UPSTREAM),
         "-c", "user.email=subarr@localhost",
         "-c", "user.name=subarr-subgen",
         "commit", "-m", msg])


# ────────────────────────────────────────────────────────────────────────
# Patch transformations (mirror update_subgen_v4.py exactly)
# ────────────────────────────────────────────────────────────────────────


T_MAIN = 'if __name__ == "__main__":'

EAGER = '''
    # [v4 PATCH] Eager model load on boot (ensures download/verify at startup)
    logging.info("--- [Startup] Eager model load check ---")
    try:
        from stable_whisper import load_faster_whisper
        _tm = load_faster_whisper(whisper_model, device=transcribe_device,
                                  compute_type=compute_type,
                                  download_root='/subgen/models')
        logging.info("--- [Startup] Model verified ---")
        if clear_vram_on_complete:
            logging.info("--- [Startup] Clearing VRAM ---")
            _tm.model.unload_model()
            del _tm
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
    except Exception as _e:
        logging.error(f"Startup eager load failed: {_e}")
    # ------------------------------------------------------------------
'''

T_TE_SIG = "def transcribe_existing(transcribe_folders, forceLanguage: LanguageCode = LanguageCode.NONE):"

NEW_TE = '''def transcribe_existing(transcribe_folders, forceLanguage : LanguageCode | None = None, reverse : bool = False):
    _orig_arg = transcribe_folders
    transcribe_folders = transcribe_folders.split("|")
    logging.info(f"Starting to search folders to see if we need to create subtitles (Reverse={reverse}).")
    logging.debug("The folders are:")

    # [v4.1 PATCH] Structured dispatch counts for /batch return.
    counts = {
        "walked": 0,
        "queued": 0,
        "skipped": 0,
        "already_in_queue": 0,
        "no_audio": 0,
        "pending_language_detect": 0,
    }

    def _tally(_result):
        if _result == "queued":
            counts["queued"] += 1
        elif _result == "skipped":
            counts["skipped"] += 1
        elif _result == "already_active":
            counts["already_in_queue"] += 1
        elif _result == "no_audio":
            counts["no_audio"] += 1
        elif _result == "detect_pending":
            counts["pending_language_detect"] += 1

    # [v4 PATCH] Collect files first, then sort with optional reverse
    file_list = []
    for path in transcribe_folders:
        logging.debug(path)
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append(file_path)

    file_list.sort(reverse=reverse)

    for file_path in file_list:
        counts["walked"] += 1
        _tally(gen_subtitles_queue(path_mapping(file_path), transcribe_or_translate, forceLanguage))

    # if the path specified was actually a single file and not a folder, process it
    # NOTE: preserves upstream/live behaviour (uses last loop 'path'); latent
    # only on single-file input, which Subgenscan never sends. Not "fixed"
    # here intentionally -- updates must not alter untested paths.
    if os.path.isfile(path):
        if has_audio(path):
            counts["walked"] += 1
            _tally(gen_subtitles_queue(path_mapping(path), transcribe_or_translate, forceLanguage))

    # Set up the observer to watch for new files
    if monitor:
        observer = Observer()
        for path in transcribe_folders:
            if os.path.isdir(path):
                handler = NewFileHandler()
                observer.schedule(handler, path, recursive=True)
        observer.start()
        logging.info("Finished searching and queueing files for transcription. Now watching for new files.")

    counts["path"] = _orig_arg
    counts["reverse"] = reverse
    return counts


'''

UPSTREAM_BATCH = ('@app.post("/batch")\n'
                  'def batch(\n'
                  '        directory: str = Query(...),\n'
                  '        forceLanguage: Union[str, None] = Query(default=None)\n'
                  '):\n'
                  '    transcribe_existing(directory, LanguageCode.from_string(forceLanguage))')

NEW_BATCH = ('@app.post("/batch")\n'
             'def batch(\n'
             '        directory: str = Query(...),\n'
             '        forceLanguage: Union[str, None] = Query(default=None),\n'
             '        reverse: bool = Query(default=False)\n'
             '):\n'
             '    # [v4.1 PATCH] Structured response: dict + 200/404 status.\n'
             '    result = transcribe_existing(directory, LanguageCode.from_string(forceLanguage), reverse)\n'
             '    status = 404 if (not isinstance(result, dict) or result.get("walked", 0) == 0) else 200\n'
             '    return JSONResponse(content=result, status_code=status)')

UPSTREAM_GSQ = '''def gen_subtitles_queue(file_path: str, transcription_type: str, force_language: LanguageCode = LanguageCode.NONE, **task_kwargs) -> None:
    global task_queue

    # Check if this file is already in the queue or being processed
    if task_queue.is_active(file_path):
        logging.debug(f"Ignored: {os.path.basename(file_path)} is already queued or processing.")
        return

    if not has_audio(file_path):
        logging.debug(f"{file_path} doesn't have any audio to transcribe!")
        return

    # Probe audio tracks once and pass to both helpers to avoid triple ffprobe
    audio_tracks = get_audio_tracks(file_path)
    audio_langs = [track['language'] for track in audio_tracks]

    force_language = choose_transcribe_language(file_path, force_language, audio_tracks=audio_tracks)

    if should_skip_file(file_path, force_language, audio_langs=audio_langs):
        return

    # Detect audio language via Whisper if no language is known and detection is enabled
    if not force_language and should_whisper_detect_audio_language:
        detect_task = {'path': file_path, 'type': "detect_language"}
        detect_task.update(task_kwargs)
        task_queue.put(detect_task)
        return

    task = {
        'path': file_path,
        'transcribe_or_translate': transcription_type,
        'force_language': force_language,
        'audio_tracks': audio_tracks,  # cached — avoids re-probing in gen_subtitles
    }
    task.update(task_kwargs)

    task_queue.put(task)
'''

NEW_GSQ = '''def gen_subtitles_queue(file_path: str, transcription_type: str, force_language: LanguageCode = LanguageCode.NONE, **task_kwargs) -> str:
    global task_queue

    # Check if this file is already in the queue or being processed
    if task_queue.is_active(file_path):
        logging.debug(f"Ignored: {os.path.basename(file_path)} is already queued or processing.")
        return "already_active"

    if not has_audio(file_path):
        logging.debug(f"{file_path} doesn't have any audio to transcribe!")
        return "no_audio"

    # Probe audio tracks once and pass to both helpers to avoid triple ffprobe
    audio_tracks = get_audio_tracks(file_path)
    audio_langs = [track['language'] for track in audio_tracks]

    force_language = choose_transcribe_language(file_path, force_language, audio_tracks=audio_tracks)

    if should_skip_file(file_path, force_language, audio_langs=audio_langs):
        return "skipped"

    # Detect audio language via Whisper if no language is known and detection is enabled
    if not force_language and should_whisper_detect_audio_language:
        detect_task = {'path': file_path, 'type': "detect_language"}
        detect_task.update(task_kwargs)
        task_queue.put(detect_task)
        return "detect_pending"

    task = {
        'path': file_path,
        'transcribe_or_translate': transcription_type,
        'force_language': force_language,
        'audio_tracks': audio_tracks,  # cached — avoids re-probing in gen_subtitles
    }
    task.update(task_kwargs)

    task_queue.put(task)
    return "queued"
'''

T_FASTAPI_IMPORT_OLD = "from fastapi.responses import StreamingResponse"
T_FASTAPI_IMPORT_NEW = "from fastapi.responses import StreamingResponse, JSONResponse"

T_DQ_HEADER = "class DeduplicatedQueue(queue.PriorityQueue):"
T_DQ_END = "task_queue = DeduplicatedQueue()"

NEW_DQ = '''class DeduplicatedQueue(queue.PriorityQueue):
    """Queue that prevents duplicates, handles priority, and tracks status.

    [v4.2 PATCH] _queued / _processing track (path -> type) instead of bare paths,
    so get_queued_tasks() / get_processing_tasks() can return structured rows for
    the GET /queue endpoint. Behaviour-preserving for is_idle / is_active and the
    put/get/mark_done lifecycle.
    """
    def __init__(self):
        super().__init__()
        self._queued = {}        # path -> task_type
        self._processing = {}    # path -> task_type
        self._lock = Lock()

    def put(self, item, block=True, timeout=None):
        with self._lock:
            task_id = item["path"]
            if task_id not in self._queued and task_id not in self._processing:
                # Priority: 0 (Detect), 1 (ASR), 2 (Transcribe)
                task_type = item.get("type", "transcribe")
                priority = 0 if task_type == "detect_language" else (1 if task_type == "asr" else 2)

                # PriorityQueue requires a tuple: (priority, tie_breaker, item)
                super().put((priority, time.time(), item), block, timeout)
                self._queued[task_id] = task_type
                return True
            return False

    def get(self, block=True, timeout=None):
        # PriorityQueue returns the tuple, we want just the item
        priority, timestamp, item = super().get(block, timeout)
        with self._lock:
            task_id = item["path"]
            task_type = self._queued.pop(task_id, item.get("type", "transcribe"))
            self._processing[task_id] = task_type
        return item

    def mark_done(self, item):
        with self._lock:
            task_id = item["path"]
            self._processing.pop(task_id, None)

    def is_idle(self):
        with self._lock:
            return self.empty() and len(self._processing) == 0

    def is_active(self, task_id):
        """Checks if a task_id is currently queued or processing."""
        with self._lock:
            return task_id in self._queued or task_id in self._processing

    def get_queued_tasks(self):
        with self._lock:
            return [{"path": p, "type": t} for p, t in self._queued.items()]

    def get_processing_tasks(self):
        with self._lock:
            return [{"path": p, "type": t} for p, t in self._processing.items()]

# Start queue
'''

T_STATUS_BLOCK = ('@app.get("/status")\n'
                  'def status():\n'
                  '    return {"version": f"Subgen {subgen_version}, '
                  'stable-ts {stable_whisper.__version__}, '
                  'faster-whisper {faster_whisper.__version__} ({docker_status})"}')

NEW_QUEUE_ENDPOINT = '''

# [v4.2 PATCH] GET /queue -- queue introspection for Subarr Monitor tab
@app.get("/queue")
def queue_status():
    queued = task_queue.get_queued_tasks()
    processing = task_queue.get_processing_tasks()
    return {
        "queued": queued,
        "processing": processing,
        "queued_count": len(queued),
        "processing_count": len(processing),
        "idle": task_queue.is_idle(),
        "version": subgen_version,
    }
'''


# ────────────────────────────────────────────────────────────────────────
# Per-patch application functions
# ────────────────────────────────────────────────────────────────────────


def patch_0002_eager_model_load() -> None:
    code = read()
    if "[v4 PATCH] Eager model load on boot" in code:
        raise SystemExit("0002: already applied")
    if T_MAIN not in code:
        raise SystemExit("0002: T_MAIN anchor not found")
    code = code.replace(T_MAIN, T_MAIN + EAGER, 1)
    write(code)
    commit("0002: eager model load on boot\n\n"
           "Loads + verifies the Whisper model at container start instead of "
           "lazily on first transcribe request. Means first-request latency is "
           "predictable and download errors fail fast on boot, not 10 minutes "
           "into a scan. Also clears VRAM after the eager-verify when "
           "clear_vram_on_complete is set.")


def patch_0003_reverse_sort() -> None:
    code = read()
    if "[v4 PATCH] Collect files first" in code:
        raise SystemExit("0003: already applied")
    if T_TE_SIG not in code:
        raise SystemExit("0003: T_TE_SIG anchor not found")
    sig_idx = code.find(T_TE_SIG)
    nxt = code.find('\nif __name__ == "__main__":', sig_idx)
    if nxt == -1:
        raise SystemExit("0003: could not find __main__ boundary")
    code = code[:sig_idx] + NEW_TE + code[nxt + 1:]
    write(code)
    commit("0003: reverse-sort transcribe_existing (full-unit replace)\n\n"
           "Replaces transcribe_existing() to (a) accept ?reverse=true so /batch "
           "can process newest files first, (b) collect-then-sort instead of "
           "walking in directory-iteration order, (c) tally outcomes per file "
           "into a structured counts dict for the /batch return shape. "
           "Subgenscan.ps1 Option 2 depends on this reverse param.")


def patch_0004_batch_structured_response() -> None:
    code = read()
    if "return JSONResponse(content=result" in code:
        raise SystemExit("0004: already applied")
    if UPSTREAM_BATCH not in code:
        raise SystemExit("0004: UPSTREAM_BATCH not found verbatim")
    code = code.replace(UPSTREAM_BATCH, NEW_BATCH, 1)
    write(code)
    commit("0004: /batch returns structured JSONResponse\n\n"
           "Was: plain implicit-None return. Now: JSONResponse(dict) with the "
           "structured counts (walked / queued / skipped / already_in_queue / "
           "no_audio / pending_language_detect) and a 200/404 status code "
           "(404 if walked==0, signals 'directory had no files'). subarr's "
           "scan_runner consumes this shape. Also adds ?reverse=true passthrough.")


def patch_0005_gsq_return_str() -> None:
    code = read()
    if 'return "queued"' in code:
        raise SystemExit("0005: already applied")
    if UPSTREAM_GSQ not in code:
        raise SystemExit("0005: UPSTREAM_GSQ not found verbatim")
    code = code.replace(UPSTREAM_GSQ, NEW_GSQ, 1)
    write(code)
    commit("0005: gen_subtitles_queue returns dispatch string\n\n"
           "Was: implicit None on every branch. Now: returns one of "
           "'queued' / 'skipped' / 'already_active' / 'no_audio' / "
           "'detect_pending' so transcribe_existing() can _tally outcomes "
           "into the /batch structured response (patch 0004). Pure addition; "
           "no caller cared about the return value pre-patch.")


def patch_0006_fastapi_jsonresponse() -> None:
    code = read()
    if T_FASTAPI_IMPORT_NEW in code:
        raise SystemExit("0006: already applied")
    if T_FASTAPI_IMPORT_OLD not in code:
        raise SystemExit("0006: T_FASTAPI_IMPORT_OLD not found")
    code = code.replace(T_FASTAPI_IMPORT_OLD, T_FASTAPI_IMPORT_NEW, 1)
    write(code)
    commit("0006: widen fastapi.responses import to include JSONResponse\n\n"
           "Required by patch 0004 (/batch returns JSONResponse). One-line "
           "import widening — the one structured string-replace v4 permits.")


def patch_0007_dq_and_queue_endpoint() -> None:
    code = read()
    if "[v4.2 PATCH] _queued / _processing track" in code:
        raise SystemExit("0007: already applied")
    dq_start = code.find(T_DQ_HEADER)
    dq_end = code.find(T_DQ_END, dq_start)
    if dq_start == -1 or dq_end == -1:
        raise SystemExit("0007: DeduplicatedQueue bounds not found")
    code = code[:dq_start] + NEW_DQ + code[dq_end:]
    # Add /queue endpoint
    if T_STATUS_BLOCK not in code:
        raise SystemExit("0007: T_STATUS_BLOCK not found for /queue insertion")
    code = code.replace(T_STATUS_BLOCK, T_STATUS_BLOCK + NEW_QUEUE_ENDPOINT, 1)
    write(code)
    commit("0007: DeduplicatedQueue type-tracking + GET /queue endpoint\n\n"
           "DeduplicatedQueue's _queued / _processing become dict[path->type] "
           "instead of bare set[path], so get_queued_tasks / "
           "get_processing_tasks return list[{path, type}] dicts. Public "
           "method signatures (put/get/mark_done/is_active/is_idle) preserved.\n\n"
           "Adds GET /queue endpoint returning {queued, processing, "
           "queued_count, processing_count, idle, version} for subarr's "
           "header counter, completion watcher, and Activity tab.")


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────


PATCHES_IN_ORDER = [
    (patch_0002_eager_model_load, "0002-eager-model-load.patch"),
    (patch_0003_reverse_sort, "0003-reverse-sort-transcribe-existing.patch"),
    (patch_0004_batch_structured_response, "0004-batch-structured-response.patch"),
    (patch_0005_gsq_return_str, "0005-gsq-return-str.patch"),
    (patch_0006_fastapi_jsonresponse, "0006-fastapi-jsonresponse-import.patch"),
    (patch_0007_dq_and_queue_endpoint, "0007-deduplicated-queue-type-tracking-and-queue-endpoint.patch"),
]


def main() -> None:
    # Ensure clean starting point: apply patch 0001 first (which we already
    # extracted), then apply 0002-0007 on top.
    print("==> resetting upstream to pinned commit")
    run(["git", "-C", str(UPSTREAM), "reset", "--hard", "HEAD"])

    print("==> applying patch 0001 (already extracted)")
    run(["git", "-C", str(UPSTREAM), "apply", "--index",
         str(PATCHES / "0001-per-language-kwargs.patch")])
    commit("0001: per-language kwargs (SUBGEN_KWARGS_LANG_<CODE>)\n\n"
           "Reads SUBGEN_KWARGS_LANG_<CODE> env vars at startup, merges the "
           "matching override into transcribe args when language is "
           "detected/forced at each transcribe site (3 sites).")

    for i, (fn, name) in enumerate(PATCHES_IN_ORDER, start=2):
        print(f"==> applying patch {name}")
        fn()

    n_total = 1 + len(PATCHES_IN_ORDER)
    print(f"==> format-patching all {n_total} patches into patches/")
    # Wipe existing .patch files first so format-patch's output is what
    # ends up in patches/.
    for p in PATCHES.glob("*.patch"):
        p.unlink()
    run(["git", "-C", str(UPSTREAM), "format-patch",
         f"-{n_total}", "--no-signature", "--zero-commit",
         "-o", str(PATCHES)])

    # format-patch produces NNNN-<commit-subject-slug>.patch — rename to
    # canonical names per the series file.
    canonical = {
        "0001-per-language-kwargs.patch": "0001",
        "0002-eager-model-load.patch": "0002",
        "0003-reverse-sort-transcribe-existing.patch": "0003",
        "0004-batch-structured-response.patch": "0004",
        "0005-gsq-return-str.patch": "0005",
        "0006-fastapi-jsonresponse-import.patch": "0006",
        "0007-deduplicated-queue-type-tracking-and-queue-endpoint.patch": "0007",
    }
    for p in sorted(PATCHES.glob("*.patch")):
        # The format-patch output starts with NNNN- where NNNN is the patch
        # number in series order. Map by leading 4 digits.
        prefix = p.name[:4]
        target_name = next((k for k, v in canonical.items() if v == prefix), None)
        if target_name and p.name != target_name:
            target = PATCHES / target_name
            if target.exists():
                target.unlink()
            p.rename(target)

    print(f"==> resetting upstream back to vanilla pin")
    run(["git", "-C", str(UPSTREAM), "reset", "--hard",
         f"HEAD~{n_total}"])

    print()
    print("done. patches in patches/:")
    for p in sorted(PATCHES.glob("*.patch")):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
