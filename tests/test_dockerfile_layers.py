"""#63: every image update re-downloaded ~4.4 GB, even for a one-line patch.

Measured on GHCR: r8 -> r9 and r9 -> r10 each shared the CUDA base layers but
shipped a NEW 4.0 GB torch layer and a new 252 MB apt layer. Two causes:

1. The release tag was declared (ARG + ENV) at the TOP of the Dockerfile. A
   changed ARG is a cache miss for every later RUN, so each release rebuilt
   apt and torch.
2. The release build had no persistent layer cache, and `pip install -U torch`
   was unpinned, so a rebuild produced a new 4 GB blob (and could silently move
   torch).

The guard: heavy, rarely-changing layers first and pinned; the security
upgrade in its own later layer, forced fresh by a date build-arg (a cached apt
layer silently stops shipping security patches -- see the subarr lesson); the
release metadata last; a registry cache on the release build.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "docker" / "Dockerfile"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
BUILD_SH = ROOT / "scripts" / "build.sh"


def _instructions() -> list[str]:
    """Dockerfile instructions with line continuations joined and comments dropped."""
    out: list[str] = []
    buf = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        out.append(buf.strip())
        buf = ""
    return out


def _index(pred) -> int:
    for i, ins in enumerate(_instructions()):
        if pred(ins):
            return i
    raise AssertionError("instruction not found")


def _torch_run() -> int:
    return _index(lambda s: s.startswith("RUN") and "torch" in s and "pip install" in s)


def test_torch_is_pinned_to_an_exact_version():
    ins = _instructions()[_torch_run()]
    assert re.search(r"\btorch==\d+\.\d+\.\d+", ins), ins
    assert re.search(r"\btorchaudio==\d+\.\d+\.\d+", ins), ins
    assert " -U " not in f" {ins} ", (
        "an unpinned upgrade can move torch and rebuild the 4 GB layer"
    )


def test_release_metadata_comes_after_every_heavy_layer():
    ins = _instructions()
    last_run = max(i for i, s in enumerate(ins) if s.startswith("RUN"))
    for name in ("RELEASE_TAG", "PATCH_REV", "UPSTREAM_VERSION"):
        first = _index(
            lambda s, n=name: s.startswith(("ARG", "ENV", "LABEL")) and n in s
        )
        assert first > last_run, (
            f"{name} is referenced at instruction {first}, before a RUN at {last_run}"
        )
    assert _index(lambda s: "SUBARR_SUBGEN_RELEASE_TAG" in s) > last_run


def test_the_package_install_before_torch_does_not_upgrade():
    ins = _instructions()
    torch = _torch_run()
    for s in ins[:torch]:
        if s.startswith("RUN") and "apt-get" in s:
            assert "apt-get upgrade" not in s, (
                "an upgrade before torch would bust torch whenever it refreshes"
            )


def test_the_security_upgrade_is_its_own_later_layer_refreshed_by_a_date_arg():
    ins = _instructions()
    torch = _torch_run()
    arg = _index(lambda s: s.startswith("ARG APT_REFRESH"))
    upgrade = _index(lambda s: s.startswith("RUN") and "apt-get upgrade" in s)
    assert torch < arg < upgrade, (torch, arg, upgrade)
    # The RUN must REFERENCE the arg, or a changed value is not a cache miss.
    assert "APT_REFRESH" in ins[upgrade], ins[upgrade]


def test_the_release_build_uses_a_registry_cache_and_a_daily_apt_refresh():
    wf = RELEASE.read_text(encoding="utf-8")
    assert re.search(
        r"cache-from:\s*type=registry,ref=ghcr\.io/coaxk/subarr-subgen:buildcache", wf
    ), "no cache-from"
    assert re.search(
        r"cache-to:\s*type=registry,ref=ghcr\.io/coaxk/subarr-subgen:buildcache,mode=max",
        wf,
    ), "no cache-to"
    assert re.search(r"APT_REFRESH=\$\{\{\s*steps\.\w+\.outputs\.\w+\s*\}\}", wf), (
        "release build does not pass APT_REFRESH"
    )


def test_local_and_ci_scan_builds_refresh_apt_too():
    sh = BUILD_SH.read_text(encoding="utf-8")
    assert "APT_REFRESH=" in sh, (
        "scripts/build.sh (PR and trivy builds) must pass APT_REFRESH"
    )
