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

