"""Helpers of the build pipeline (windows/build): requirement splitting, manifest and THIRD_PARTY."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "windows" / "build"


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"),
        BUILD / f"{name}.py",
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = """\
django==5.2.18 ; sys_platform == 'win32' \\
    --hash=sha256:aaa \\
    --hash=sha256:bbb
    # via paperless-ngx
numpy==2.0.0 \\
    --hash=sha256:ccc
"""
EVERYTHING = (
    BASE
    + """\
torch==2.14.0+cpu ; sys_platform == 'win32' \\
    --hash=sha256:ddd
    # via sentence-transformers
torch==2.14.0 ; sys_platform == 'darwin' \\
    --hash=sha256:eee
sympy==1.14.0 \\
    --hash=sha256:fff
"""
)


@pytest.mark.skipif(not BUILD.is_dir(), reason="needs a full checkout")
def test_split_keeps_only_the_extra_entries_with_their_hashes() -> None:
    split = load("split_requirements")
    out = split.split(BASE, EVERYTHING)
    assert "django" not in out
    assert "numpy" not in out
    assert (
        "torch==2.14.0+cpu ; sys_platform == 'win32' \\\n    --hash=sha256:ddd" in out
    )
    assert "sympy==1.14.0" in out
    assert "--hash=sha256:aaa" not in out  # the hashes of base packages do not leak in
    assert "# via sentence-transformers" in out


@pytest.mark.skipif(not BUILD.is_dir(), reason="needs a full checkout")
def test_split_can_add_the_extra_index() -> None:
    split = load("split_requirements")
    out = split.split(BASE, EVERYTHING, "https://example.test/cpu")
    assert out.splitlines()[0] == "--extra-index-url https://example.test/cpu"


@pytest.mark.skipif(not BUILD.is_dir(), reason="needs a full checkout")
def test_entries_parse_blocks() -> None:
    split = load("split_requirements")
    found = split.entries(BASE)
    assert [first.split("==")[0] for first, _ in found] == ["django", "numpy"]
    assert len(found[0][1]) == 4


@pytest.mark.skipif(not BUILD.is_dir(), reason="needs a full checkout")
def test_every_download_in_the_manifest_is_pinned() -> None:
    manifest = json.loads((BUILD / "manifest.json").read_text(encoding="utf-8"))
    ids = [i["id"] for i in manifest["inputs"]]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for item in manifest["inputs"]:
        assert item["scope"] in {"bundled", "dev", "optional"}, item["id"]
        assert item["license"], item["id"]
        if item["url"]:
            assert item["url"].startswith("https://"), item["id"]
            assert len(item["sha256"]) == 64, item["id"]
            assert item["file"], item["id"]
        else:
            assert item["sha256"] is None, item["id"]


@pytest.mark.skipif(not BUILD.is_dir(), reason="needs a full checkout")
def test_third_party_md_matches_the_manifest() -> None:
    third = load("make-third-party")
    inputs = json.loads((BUILD / "manifest.json").read_text(encoding="utf-8"))["inputs"]
    current = third.TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert third.render(current, inputs) == current, (
        "windows/THIRD_PARTY.md is out of date: run python windows/build/make-third-party.py"
    )
