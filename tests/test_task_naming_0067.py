"""Patch 0067 (coaxk/subarr-subgen#89): naming and skip checks follow the
per-file task.

subgen already transcribed with the per-file task, but the naming helper,
name_subtitle, should_skip_file and the language-detection hop read the global
transcribe_or_translate. A per-request task=transcribe on a translate install
therefore wrote Spanish text under an `.en.srt` name, and a per-request
task=translate on a transcribe install wrote English text under the source
language's name (or skipped the wrong sidecar).

These tests exec the patched functions out of upstream/subgen.py; they never
import subgen itself (torch/faster_whisper are not installed here).
"""

from __future__ import annotations

import ast
import contextvars
import importlib.util
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SUBGEN = ROOT / "upstream" / "subgen.py"
LANGUAGE_CODE = ROOT / "upstream" / "language_code.py"


@pytest.fixture(autouse=True)
def _patched_tree():
    if "[v4.40 PATCH #669]" not in SUBGEN.read_text(encoding="utf-8"):
        pytest.fail("run scripts/apply-patches.sh first")


def _load_language_code():
    spec = importlib.util.spec_from_file_location("language_code_0067", LANGUAGE_CODE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LanguageCode


LanguageCode = _load_language_code()
ES = LanguageCode.from_string("es")


def _source() -> str:
    return SUBGEN.read_text(encoding="utf-8")


def load(*names, **values) -> dict:
    """Compile the named top-level functions out of subgen.py into a fresh
    namespace pre-filled with `values` (module globals and stubs)."""
    tree = ast.parse(_source())
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            wanted.append(node)
    missing = [name for name in names if name not in {n.name for n in wanted}]
    assert not missing, f"functions not found in patched subgen.py: {missing}"
    module = ast.Module(body=wanted, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "os": os,
        "logging": __import__("logging"),
        "contextvars": contextvars,
        "LanguageCode": LanguageCode,
    }
    namespace.update(values)
    exec(compile(module, str(SUBGEN), "exec"), namespace)
    return namespace


NAMING = {
    "subtitle_language_name": "",
    "subtitle_language_naming_type": "ISO_639_1",
    "show_in_subname_subgen": False,
    "show_in_subname_model": False,
    "whisper_model": "medium",
}


def _naming_ns(transcribe_or_translate, **overrides):
    values = dict(NAMING)
    values.update(overrides)
    values["transcribe_or_translate"] = transcribe_or_translate
    return load(
        "define_subtitle_language_naming",
        "_effective_task",
        **values,
    )


# ── N1-N7: define_subtitle_language_naming ──────────────────────────────


def test_n1_per_file_transcribe_overrides_global_translate():
    ns = _naming_ns("translate")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1", task="transcribe") == "es"


def test_n2_per_file_translate_overrides_global_transcribe():
    ns = _naming_ns("transcribe")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1", task="translate") == "en"


def test_n3_absent_task_keeps_global_translate():
    ns = _naming_ns("translate")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1") == "en"


def test_n4_absent_task_keeps_global_transcribe():
    ns = _naming_ns("transcribe")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1") == "es"


def test_n5_fixed_subtitle_language_name_still_wins():
    ns = _naming_ns("transcribe", subtitle_language_name="xx")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1", task="translate") == "xx"


def test_n6_uppercase_task_is_lowercased():
    ns = _naming_ns("transcribe")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_1", task="TRANSLATE") == "en"


def test_n7_non_default_naming_type_follows_task():
    ns = _naming_ns("transcribe", subtitle_language_naming_type="ISO_639_2_B")
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_2_B", task="translate") == "eng"
    assert ns["define_subtitle_language_naming"](ES, "ISO_639_2_B", task="transcribe") == "spa"


# ── M1: name_subtitle ───────────────────────────────────────────────────


def _name_ns(transcribe_or_translate):
    values = dict(NAMING)
    values["transcribe_or_translate"] = transcribe_or_translate
    return load(
        "name_subtitle",
        "define_subtitle_language_naming",
        "_effective_task",
        **values,
    )


def test_m1_name_subtitle_uses_the_per_file_task():
    ns = _name_ns("translate")
    assert ns["name_subtitle"]("/m/a.mkv", ES, task="transcribe") == "/m/a.es.srt"
    assert ns["name_subtitle"]("/m/a.mkv", ES) == "/m/a.en.srt"


# ── G1-G2: gen_subtitles ────────────────────────────────────────────────


class _GenResult:
    language = "es"

    def __init__(self, record):
        self._record = record

    def to_srt_vtt(self, path=None, word_level=False, **kwargs):
        if isinstance(path, str):
            self._record["srt_path"] = path


class _GenModel:
    def __init__(self, record):
        self._record = record

    def transcribe(self, data, **kwargs):
        self._record["model_task"] = kwargs.get("task")
        return _GenResult(self._record)


def _gen_ns(transcribe_or_translate):
    record = {}
    values = dict(NAMING)
    values.update(
        {
            "transcribe_or_translate": transcribe_or_translate,
            "start_model": lambda *a, **k: None,
            "delete_model": lambda *a, **k: None,
            "appendLine": lambda *a, **k: None,
            "is_audio_file_extension": lambda *a, **k: False,
            "handle_multiple_audio_tracks": lambda *a, **k: None,
            "ProgressHandler": lambda name: None,
            "custom_regroup": "default",
            "kwargs": {},
            "language_specific_kwargs": {},
            "word_level_highlight": False,
            "lrc_for_audio_files": False,
            "task_results": {},
            "task_results_lock": threading.Lock(),
            "send_completion_webhook": lambda *a, **k: record.setdefault("webhook", a),
            "model": _GenModel(record),
        }
    )
    ns = load(
        "gen_subtitles",
        "name_subtitle",
        "define_subtitle_language_naming",
        "_effective_task",
        **values,
    )
    return ns, record


def test_g1_gen_subtitles_names_with_per_file_transcribe():
    ns, record = _gen_ns("translate")
    ns["gen_subtitles"]("/m/a.mkv", "transcribe")
    assert record.get("srt_path") == "/m/a.es.srt"
    assert record.get("model_task") == "transcribe"


def test_g2_gen_subtitles_names_with_per_file_translate():
    ns, record = _gen_ns("transcribe")
    ns["gen_subtitles"]("/m/a.mkv", "translate")
    assert record.get("srt_path") == "/m/a.en.srt"
    assert record.get("model_task") == "translate"


# ── S1-S4: should_skip_file ─────────────────────────────────────────────


def _skip_ns(transcribe_or_translate, existing):
    asked = []

    def subtitle_exists_in_language(path, lang, **kwargs):
        asked.append(lang)
        return False

    fake_os = types.SimpleNamespace(
        path=types.SimpleNamespace(
            basename=os.path.basename,
            splitext=os.path.splitext,
            join=os.path.join,
            dirname=os.path.dirname,
            exists=lambda p: p in existing,
        )
    )
    values = dict(NAMING)
    values.update(
        {
            "transcribe_or_translate": transcribe_or_translate,
            "os": fake_os,
            "is_audio_file_extension": lambda *a, **k: False,
            "get_audio_languages": lambda *a, **k: [ES],
            "get_subtitle_languages": lambda *a, **k: [],
            "has_internal_subtitle_in_language": lambda *a, **k: False,
            "has_external_subtitle_in_language": lambda *a, **k: False,
            "subtitle_exists_in_language": subtitle_exists_in_language,
            "lrc_for_audio_files": False,
            "skip_unknown_language": False,
            "skip_if_no_audio_language_but_subtitles_exist": False,
            "limit_to_preferred_audio_languages": False,
            "preferred_audio_languages": [],
            "skip_audio_languages": [],
            "skip_if_internal_sub_language": LanguageCode.NONE,
            "skip_subtitle_languages": [],
            "skip_if_external_sub_exists": False,
            "only_match_subgen_subtitles": False,
            "skip_if_target_subtitle_exists": True,
            "_skip_reason": contextvars.ContextVar("test_skip_reason", default=None),
            "_target_sub_internal": contextvars.ContextVar("test_target_sub", default=False),
        }
    )
    ns = load(
        "should_skip_file",
        "name_subtitle",
        "define_subtitle_language_naming",
        "_effective_task",
        "_skip_because",
        **values,
    )
    return ns, asked


def test_s1_skip_check_uses_per_file_transcribe_for_output_name():
    ns, asked = _skip_ns("translate", {"/m/a.es.srt"})
    skipped = ns["should_skip_file"]("/m/a.mkv", ES, audio_langs=[ES], task="transcribe")
    assert skipped is True
    assert ns["_skip_reason"].get() == "output_exists"
    assert asked == [ES]


def test_s2_skip_check_uses_per_file_translate_for_output_name():
    ns, asked = _skip_ns("transcribe", {"/m/a.en.srt"})
    skipped = ns["should_skip_file"]("/m/a.mkv", ES, audio_langs=[ES], task="translate")
    assert skipped is True
    assert ns["_skip_reason"].get() == "output_exists"
    assert asked == [LanguageCode.ENGLISH]


def test_s3_other_tasks_sidecar_does_not_cause_a_skip():
    ns, _asked = _skip_ns("transcribe", {"/m/a.es.srt"})
    assert ns["should_skip_file"]("/m/a.mkv", ES, audio_langs=[ES], task="translate") is False


def test_s4_absent_task_keeps_old_skip_behaviour():
    ns, _asked = _skip_ns("translate", {"/m/a.en.srt"})
    assert ns["should_skip_file"]("/m/a.mkv", ES, audio_langs=[ES]) is True


# ── Q1-Q2: gen_subtitles_queue ──────────────────────────────────────────


def _queue_ns(choose_language):
    put = []
    seen = {}

    class _Queue:
        def is_active(self, path):
            return False

        def put(self, task):
            put.append(task)

    def should_skip_file(*args, **kwargs):
        seen.update(kwargs)
        return False

    ns = load(
        "gen_subtitles_queue",
        task_queue=_Queue(),
        has_audio=lambda *a, **k: True,
        get_audio_tracks=lambda *a, **k: [{"language": ES}],
        choose_transcribe_language=choose_language,
        should_skip_file=should_skip_file,
        should_whisper_detect_audio_language=True,
        transcribe_or_translate="transcribe",
    )
    return ns, put, seen


def test_q1_queued_task_and_skip_check_carry_the_per_file_task():
    ns, put, seen = _queue_ns(lambda path, lang, **kwargs: lang)
    assert ns["gen_subtitles_queue"]("/m/a.mkv", "translate", ES) == "queued"
    assert put[0]["transcribe_or_translate"] == "translate"
    assert seen["task"] == "translate"


def test_q2_detect_task_carries_the_per_file_task():
    ns, put, _seen = _queue_ns(lambda path, lang, **kwargs: LanguageCode.NONE)
    assert (
        ns["gen_subtitles_queue"]("/m/a.mkv", "translate", LanguageCode.NONE)
        == "detect_pending"
    )
    assert put[0]["transcribe_or_translate"] == "translate"


# ── D1-D3: detect_language_task ─────────────────────────────────────────


def _detect_ns(transcribe_or_translate):
    class _DetectResult:
        language = "es"

    class _DetectModel:
        def transcribe(self, data, **kwargs):
            return _DetectResult()

    return load(
        "detect_language_task",
        transcribe_or_translate=transcribe_or_translate,
        start_model=lambda *a, **k: None,
        delete_model=lambda *a, **k: None,
        extract_audio_segment_to_memory=lambda *a, **k: b"",
        model=_DetectModel(),
        detect_language_length=30,
        detect_language_offset=0,
    )


def test_d1_follow_up_task_keeps_the_per_file_task():
    ns = _detect_ns("transcribe")
    task = ns["detect_language_task"](
        "/m/a.mkv",
        original_task_data={
            "path": "/m/a.mkv",
            "type": "detect_language",
            "transcribe_or_translate": "translate",
        },
    )
    assert task["transcribe_or_translate"] == "translate"
    assert task["type"] == "transcribe"


def test_d2_follow_up_task_falls_back_to_global_translate():
    ns = _detect_ns("translate")
    task = ns["detect_language_task"](
        "/m/a.mkv",
        original_task_data={"path": "/m/a.mkv", "type": "detect_language"},
    )
    assert task["transcribe_or_translate"] == "translate"


def test_d3_follow_up_task_falls_back_to_global_transcribe():
    ns = _detect_ns("transcribe")
    task = ns["detect_language_task"](
        "/m/a.mkv",
        original_task_data={"path": "/m/a.mkv", "type": "detect_language"},
    )
    assert task["transcribe_or_translate"] == "transcribe"


# ── V0-V1: validator ────────────────────────────────────────────────────


def test_v0_validator_passes_on_the_patched_tree():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate-patched.py")],
        cwd=ROOT,
    )
    assert result.returncode == 0


def _validator_module():
    path = ROOT / "scripts" / "validate-patched.py"
    spec = importlib.util.spec_from_file_location("validate_patched_0067", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_span(source: str, name: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = source.splitlines(keepends=True)
            start = node.lineno - 1
            end = node.end_lineno
            return "".join(lines[start:end])
    raise AssertionError(f"{name} not found")


def _replace_in_function(source: str, name: str, old: str, new: str) -> str:
    span = _function_span(source, name)
    assert old in span, f"{old!r} not in {name}"
    replaced_span = span.replace(old, new, 1)
    assert replaced_span != span
    return source.replace(span, replaced_span, 1)


def test_v1_validator_goes_red_when_any_wiring_is_reverted():
    module = _validator_module()
    source = _source()

    module.validate_task_naming(ast.parse(source))

    detect_literal = (
        "        detect_task = {\n"
        "            'path': file_path,\n"
        "            'type': \"detect_language\",\n"
        "            'transcribe_or_translate': transcription_type,\n"
        "        }"
    )
    detect_oneliner = "        detect_task = {'path': file_path, 'type': \"detect_language\"}"

    # (d) lives inside the transcribe dict, which contains the same entry text
    # as the detect dict, so locate it after the `task = {` line.
    queue_span = _function_span(source, "gen_subtitles_queue")
    task_dict_at = queue_span.index("\n    task = {")
    head = queue_span[:task_dict_at]
    tail = queue_span[task_dict_at:].replace(
        "'transcribe_or_translate': transcription_type,",
        "'transcribe_or_translate': transcribe_or_translate,",
        1,
    )
    assert tail != queue_span[task_dict_at:]
    mutated_d = source.replace(queue_span, head + tail, 1)

    mutations = [
        (
            source.replace(
                "name_subtitle(file_path, output_language, task=transcription_type)",
                "name_subtitle(file_path, output_language)",
                1,
            )
        ),
        _replace_in_function(
            source,
            "should_skip_file",
            "_effective_task(task) == 'translate'",
            "transcribe_or_translate == 'translate'",
        ),
        source.replace(detect_literal, detect_oneliner, 1),
        mutated_d,
        source.replace(
            "name_subtitle(file_path, target_language, task=task)",
            "name_subtitle(file_path, target_language, task=None)",
            1,
        ),
    ]
    for i, mutated in enumerate(mutations):
        assert mutated != source, f"mutation {i} changed nothing"
        with pytest.raises(SystemExit):
            module.validate_task_naming(ast.parse(mutated))
