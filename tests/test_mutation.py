from chipevolve.services.mutation import BASELINE_BLOCK, apply_mux_restructure, plan_mux_restructure


def test_mutation_is_local_and_explainable(tmp_path) -> None:
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    target = rtl / "alu.sv"
    target.write_text(f"module alu;\n{BASELINE_BLOCK}\nendmodule\n", encoding="utf-8")
    plan = plan_mux_restructure([])
    result = apply_mux_restructure(tmp_path, plan)
    changed = target.read_text(encoding="utf-8")
    assert result.changed_files == ["rtl/alu.sv"]
    assert "unique case (op)" in changed
    assert "priority chain" not in changed

