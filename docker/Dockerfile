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

LABEL org.opencontainers.image.title="subarr-subgen"
LABEL org.opencontainers.image.description="McCloudS/subgen + subarr-required patches"
LABEL org.opencontainers.image.source="https://github.com/coaxk/subarr-subgen"
LABEL org.opencontainers.image.licenses="MIT"
LABEL subarr.subgen.upstream_version="${UPSTREAM_VERSION}"
LABEL subarr.subgen.patch_rev="${PATCH_REV}"
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

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "launcher.py"]
