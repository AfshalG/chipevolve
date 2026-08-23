from chipevolve.services.integrity import integrity_matches, protected_hashes


def test_protected_hash_detects_changes(tmp_path) -> None:
    protected = tmp_path / "tb"
    protected.mkdir()
    testbench = protected / "alu_tb.sv"
    testbench.write_text("original", encoding="utf-8")
    before = protected_hashes(tmp_path, ["tb/**"])
    testbench.write_text("weakened", encoding="utf-8")
    after = protected_hashes(tmp_path, ["tb/**"])
    assert not integrity_matches(before, after)



def test_glob_star_star_matches_files_not_just_directories(tmp_path) -> None:
    """Regression: Path.glob("tb/**") yields only the DIRECTORY tb.

    The is_file() filter then dropped it, so protected_hashes returned {} for
    every pattern and integrity_matches({}, {}) was always True — the
    reward-hacking gate never fired.
    """
    (tmp_path / "tb").mkdir()
    (tmp_path / "tb" / "alu_tb.sv").write_text("assert", encoding="utf-8")
    (tmp_path / "tb" / "nested").mkdir()
    (tmp_path / "tb" / "nested" / "helper.sv").write_text("helper", encoding="utf-8")
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "alu.sv").write_text("design", encoding="utf-8")

    hashes = protected_hashes(tmp_path, ["tb/**"])
    assert "tb/alu_tb.sv" in hashes
    assert "tb/nested/helper.sv" in hashes
    assert "rtl/alu.sv" not in hashes, "mutable RTL must not be protected"


def test_empty_protected_set_is_not_a_pass(tmp_path) -> None:
    """A misconfigured `protected` list must not look like a clean run."""
    assert not integrity_matches({}, {})
