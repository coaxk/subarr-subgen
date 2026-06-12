# subarr-subgen — patched McCloudS/subgen image.
#
# Layer structure mirrors upstream's Dockerfile (apt + torch + pip in separate
# layers for cache efficiency). NOTE: this image bumps the CUDA base to 12.8
# (upstream is still on 12.3) — see the FROM line. Build context is build/,
# which scripts/build.sh produces by:
#
#   1. cp -a upstream/. build/   (vanilla source tree)
#   2. apply patches in build/   (via apply-patches.sh in upstream/, then
#      build.sh recopies the patched tree)
#
# So when this Dockerfile COPYs subgen.py, it's the patched one.
#
# Differs from upstream Dockerfile by:
#   - CUDA base bumped 12.3 -> 12.8 (Blackwell/sm_120 support — see below)
#   - adding OCI image labels for version/source provenance
#   - taking UPSTREAM_VERSION + PATCH_REV build-args
#
# Same deps, same entrypoint, same CMD — drop-in.

# CUDA 12.8 base (was 12.3.2-base): CUDA 12.3's cuBLAS has no sm_120 kernels, so
# every transcription fails with CUBLAS_STATUS_NOT_SUPPORTED on NVIDIA Blackwell
# / RTX 50xx GPUs (#163) — CTranslate2 4.5+ has the Blackwell kernels but the
# cuBLAS underneath was too old. 12.8 ships sm_120 cuBLAS; the cudnn-runtime
# flavour also bundles cuBLAS + cuDNN at the matching version (the old -base
# relied on whatever cuBLAS happened to be present). Kept on ubuntu22.04
# (python3.10) to minimise the blast radius.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ARG UPSTREAM_VERSION=unknown
ARG PATCH_REV=unknown
# [r9 / subarr#224] The GHCR release tag this image was built from
# (e.g. v2026.05.3-r9). Emitted in the /queue caps body as
# subarr_subgen_release_tag so subarr's update check compares
# like-for-like instead of patch-rev vs date-tag (which made every
# install show a permanent fake "update available").
ARG RELEASE_TAG=dev
ENV SUBARR_SUBGEN_RELEASE_TAG="${RELEASE_TAG}"

LABEL org.opencontainers.image.title="subarr-subgen"
LABEL org.opencontainers.image.description="McCloudS/subgen + subarr-required patches"
LABEL org.opencontainers.image.source="https://github.com/coaxk/subarr-subgen"
LABEL org.opencontainers.image.licenses="MIT"
LABEL subarr.subgen.upstream_version="${UPSTREAM_VERSION}"
LABEL subarr.subgen.patch_rev="${PATCH_REV}"
LABEL subarr.subgen.release_tag="${RELEASE_TAG}"
LABEL subarr.subgen.upstream_source="https://github.com/McCloudS/subgen"

# Apt packages — own layer so pip changes don't re-run apt.
# `apt-get upgrade` pulls base-image security patches (the cuda:12.8 base
# ships gnupg 2.2.27-3ubuntu2.1, flagged HIGH by trivy as CVE-2025-68973;
# fix is 2.2.27-3ubuntu2.5). Patching at build time keeps the trivy gate
# green legitimately rather than suppressing the finding, and hardens the
# rest of the base packages too.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        ffmpeg python3 python3-pip curl gosu tzdata

# Torch — large and rarely changes; own layer so requirements.txt changes don't bust it
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install -U torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# App dependencies — only rebuilds when requirements.txt changes
COPY requirements.txt /
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install -U -r /requirements.txt \
    && apt-get purge -y --auto-remove python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /subgen

# App files last — changes here don't bust the layers above.
# subgen.py is the PATCHED version (apply-patches.sh has already run).
COPY launcher.py subgen.py language_code.py /subgen/

RUN mkdir -p /cache && chmod 777 /cache

ENV XDG_CACHE_HOME=/cache \
    HF_HOME=/cache/huggingface \
    MPLCONFIGDIR=/cache/matplotlib \
    PYTHONUNBUFFERED=1

# [r8] Bake the subarr-tuned subtitle segmentation as the default. "v2-strongpad"
# won the #168 regroup arena (4 audio langs x 6 configs, full files) and held on
# held-out languages (de/sr): median CPS ~13-15, %>25 CPS ~8-14%, zero sub-0.5s
# micro-cues. Overridable at runtime — set CUSTOM_REGROUP="" to disable, or to
# your own DSL. (subgen reads CUSTOM_REGROUP from the environment.)
ENV CUSTOM_REGROUP="cm_sp=.* /。/?/？_sg=.5_mg=.3++84_p=.3+.7+1.5_sl=42++++++1"

# [r9] Bake the Phase-1 kwargs research as the image default. These are the
# hardware-INDEPENDENT anti-failure settings (hallucination/looping fixes,
# each issue-cited in coaxk/subarr-subgen docs): temperature ladder re-enables
# Whisper's fallback, log_prob -0.8 tightens the hallucination gate,
# length_penalty 1.0 stops hallucinated bursts being cheaper than full
# transcriptions (faster-whisper #569), VAD timing fixes over-merging
# (faster-whisper #477). Overridable: any SUBGEN_KWARGS you set wins.
# Contested knobs (condition_on_previous_text=false, VAD timing) are called
# out in the r9 release notes.
ENV SUBGEN_KWARGS='{"no_speech_threshold": 0.6, "vad_filter": true, "vad_parameters": {"threshold": 0.5, "min_speech_duration_ms": 250, "min_silence_duration_ms": 500, "speech_pad_ms": 600}, "condition_on_previous_text": false, "beam_size": 5, "patience": 1.0, "length_penalty": 1.0, "repetition_penalty": 1.05, "no_repeat_ngram_size": 3, "compression_ratio_threshold": 2.4, "log_prob_threshold": -0.8, "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]}'

# [r9] The one per-language override that survived the 17-override prune
# (JA subtitle convention plausibly matches the longer length_penalty).
ENV SUBGEN_KWARGS_LANG_JA='{"patience": 1.0, "length_penalty": 1.3}'

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "launcher.py"]
