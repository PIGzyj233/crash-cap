import json

import pytest

from .fixture_source import fixture_source_root


def test_compiler_root_is_not_rebased_to_test_checkout(tmp_path):
    root = r"D:\a\crash-cap\crash-cap"
    (tmp_path / "manifest.json").write_text(
        json.dumps({"generator": {"source_root": root}}), encoding="utf-8"
    )
    assert fixture_source_root(tmp_path) == root


@pytest.mark.parametrize("root", [None, "relative/path", "/linux/test/checkout", 17])
def test_missing_or_non_compiler_root_requires_regeneration(tmp_path, root):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"generator": {"source_root": root}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="rerun build_p0_b01"):
        fixture_source_root(tmp_path)
