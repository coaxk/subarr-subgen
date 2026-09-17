#!/usr/bin/env python3
"""Torch-upgrade gate: does a torch/torchaudio pair still run subgen's paths?

Written for #27 (CVE-2025-3000), where torch had to move from 2.11+cu128 to
2.13+cu129 while torchaudio's last release is 2.11. Run it inside an image
(or a throwaway container of one) and compare two runs file by file:

    docker run --rm --gpus all --entrypoint python3 \\
      -v "$PWD/gate:/work" <image> /work/torch-gate.py --work /work --clip /work/clip.wav

Every output is tagged with the torch version (`<name>_<torch>.<ext>`), so a
baseline run and a candidate run can sit in the same directory:

    report_<v>.json   pass/fail, values and warnings per step
    resample_<v>.pt   torchaudio.functional.resample of a fixed signal on CUDA
    fw_<v>.txt        faster-whisper transcript (segment timings + text)
    sts_<v>.txt       stable-ts over faster-whisper transcript (subgen's path)

What the 2026-09-17 run established, so a future reader knows what "normal" is:
  - torchaudio refuses to import when its CUDA build differs from torch's
    ("compiled with different CUDA versions"). Pair them from the same index.
  - `torchaudio.save` fails on r10 already (needs TorchCodec). That stable-ts
    path is unused by subgen; a failure there is not a regression.
  - With a matched pair, resample output was bit-identical and both
    transcripts were identical to r10.

Cut a clip with, for example:
    ffmpeg -ss 300 -t 30 -i <episode> -map 0:a:0 -ac 1 -ar 16000 clip.wav

Exit code is 0 only when every step except `torchaudio.save` passes, and when
--expect-torch (if given) matches the installed torch. A candidate run that
silently kept the old torch is the failure this guards: r10 ships without pip,
so an in-container upgrade can fail and leave the baseline in place.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import warnings

KNOWN_BROKEN = {"torchaudio.save"}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--work", default="/work", help="output directory (default /work)")
    ap.add_argument(
        "--clip",
        default=None,
        help="16 kHz mono WAV to transcribe (default <work>/clip.wav)",
    )
    ap.add_argument(
        "--model", default="base", help="faster-whisper model (default base)"
    )
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument(
        "--expect-torch",
        default=None,
        help="fail unless torch.__version__ starts with this",
    )
    args = ap.parse_args()

    work = args.work
    clip = args.clip or os.path.join(work, "clip.wav")
    report: dict = {}

    def step(name, fn):
        t0 = time.time()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                value = fn()
            report[name] = {
                "ok": True,
                "value": value,
                "warnings": sorted(
                    {f"{w.category.__name__}: {str(w.message)[:160]}" for w in caught}
                ),
                "s": round(time.time() - t0, 2),
            }
        except Exception as e:  # noqa: BLE001 - a gate records every failure
            report[name] = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}"[:400],
                "trace": traceback.format_exc()[-800:],
            }
        mark = (
            "OK  "
            if report[name]["ok"]
            else ("KNOWN" if name in KNOWN_BROKEN else "FAIL")
        )
        print(f"[{mark}] {name}", flush=True)

    import torch

    tag = torch.__version__.split("+")[0]

    def versions():
        import ctranslate2
        import faster_whisper

        out = {
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "ctranslate2": ctranslate2.__version__,
            "ct2_cuda_devices": ctranslate2.get_cuda_device_count(),
            "faster_whisper": faster_whisper.__version__,
        }
        if args.device == "cuda":
            out["gpu_tensor_sum"] = float(
                (torch.ones(1024, device="cuda") * 2).sum().item()
            )
        if args.expect_torch and not torch.__version__.startswith(args.expect_torch):
            raise RuntimeError(
                f"expected torch {args.expect_torch}*, found {torch.__version__}"
            )
        return out

    def import_torchaudio():
        import torchaudio

        return {"torchaudio": torchaudio.__version__}

    def import_stable_whisper():
        import stable_whisper
        import stable_whisper.audio.utils  # noqa: F401  (imports torchaudio at module load)

        return {"stable_whisper": stable_whisper.__version__}

    def resample():
        import torchaudio

        g = torch.Generator().manual_seed(0)
        x = torch.randn(1, 48000 * 3, generator=g).to(args.device)
        y = torchaudio.functional.resample(x, 48000, 16000)
        torch.save(y.cpu(), os.path.join(work, f"resample_{tag}.pt"))
        return {
            "shape": list(y.shape),
            "device": str(y.device),
            "mean": float(y.mean()),
            "std": float(y.std()),
        }

    def save_wav():
        import torchaudio

        g = torch.Generator().manual_seed(1)
        wav = (torch.rand(1, 16000, generator=g) * 2 - 1) * 0.1
        path = os.path.join(work, f"save_{tag}.wav")
        torchaudio.save(path, wav, 16000)
        return {"bytes": os.path.getsize(path)}

    def faster_whisper_transcribe():
        from faster_whisper import WhisperModel

        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=os.path.join(work, "models"),
        )
        segments, info = model.transcribe(
            clip,
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"threshold": 0.35},
        )
        lines = [f"{s.start:.2f}-{s.end:.2f} {s.text.strip()}" for s in segments]
        with open(os.path.join(work, f"fw_{tag}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return {"segments": len(lines), "language": info.language}

    def stable_ts_transcribe():
        import stable_whisper

        model = stable_whisper.load_faster_whisper(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=os.path.join(work, "models"),
        )
        fn = getattr(model, "transcribe_stable", None) or model.transcribe
        result = fn(clip, language="en", beam_size=5)
        lines = [f"{s.start:.2f}-{s.end:.2f} {s.text.strip()}" for s in result.segments]
        with open(os.path.join(work, f"sts_{tag}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return {"segments": len(lines), "method": fn.__name__}

    step("versions", versions)
    step("import torchaudio", import_torchaudio)
    step("import stable_whisper", import_stable_whisper)
    step("torchaudio resample", resample)
    step("torchaudio.save", save_wav)
    step("faster-whisper transcribe", faster_whisper_transcribe)
    step("stable-ts transcribe via faster-whisper", stable_ts_transcribe)

    with open(os.path.join(work, f"report_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    failed = [k for k, v in report.items() if not v["ok"] and k not in KNOWN_BROKEN]
    print("failed:", failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
