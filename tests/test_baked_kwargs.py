"""The image's baked SUBGEN_KWARGS (docker/Dockerfile) are the defaults every
install runs unless it sets its own. Two things about them are load-bearing:

1. They must parse as JSON. subgen once read this variable with
   ast.literal_eval, which cannot parse JSON true/false/null, so a valid-looking
   value silently became {} and the tuned defaults never applied (2026-06-04).

2. The Silero VAD threshold is 0.35 (subarr#543). At 0.5 the VAD pre-filter cut
   whispered and under-score dialogue before Whisper saw it. Corpus sweep, #171
   Phase 2 clips, zero run-to-run noise: authored-subtitle recall 72.63% -> 74.18%,
   share of captioning outside authored subs flat at ~24.3%. Whisper's own
   no_speech_threshold was ruled out: 0.6 -> 0.4 gave byte-identical output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "docker" / "Dockerfile"


def _env(name: str) -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(rf"^ENV {name}='(.*)'\s*$", text, re.MULTILINE)
    assert m, f"ENV {name}='...' not found in {DOCKERFILE}"
    return m.group(1)


def test_baked_kwargs_are_valid_json_objects():
    for name in ("SUBGEN_KWARGS", "SUBGEN_KWARGS_LANG_JA"):
        assert isinstance(json.loads(_env(name)), dict), name


def test_vad_filter_is_on_with_threshold_035():
    kw = json.loads(_env("SUBGEN_KWARGS"))
    assert kw["vad_filter"] is True
    assert kw["vad_parameters"]["threshold"] == 0.35


def test_vad_timing_and_decoder_gates_are_unchanged():
    # #543 moved ONE knob. The timing values and the decoder gates were measured
    # alongside it and must not drift in the same change.
    kw = json.loads(_env("SUBGEN_KWARGS"))
    assert kw["vad_parameters"]["min_speech_duration_ms"] == 250
    assert kw["vad_parameters"]["min_silence_duration_ms"] == 500
    assert kw["vad_parameters"]["speech_pad_ms"] == 600
    assert kw["no_speech_threshold"] == 0.6
    assert kw["log_prob_threshold"] == -0.8
