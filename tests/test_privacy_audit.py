"""Privacy audit tests for public CI checks."""

from pathlib import Path

from vibedft.core.privacy_audit import audit_privacy


def test_privacy_audit_flags_private_tokens_in_scanned_source(tmp_path: Path):
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("cluster = 'private-cluster'\n", encoding="utf-8")

    result = audit_privacy(
        root=tmp_path,
        paths=["src"],
        private_tokens=["private-cluster"],
    )

    assert not result.ok
    assert result.violations[0].relative_path == "src/module.py"
    assert result.violations[0].matched == "private-cluster"


def test_privacy_audit_respects_explicit_excluded_paths(tmp_path: Path):
    template = tmp_path / "tests" / "Templates" / "rx.in"
    template.parent.mkdir(parents=True)
    template.write_text("pseudo_dir = '/home/private-user/software/qe'\n", encoding="utf-8")

    result = audit_privacy(
        root=tmp_path,
        paths=["tests"],
        excludes=["tests/Templates"],
        private_tokens=["private-user"],
    )

    assert result.ok
    assert result.violations == []
