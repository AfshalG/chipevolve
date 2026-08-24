from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chipevolve.domain.models import MutationPlan


@dataclass(frozen=True)
class MutationResult:
    plan: MutationPlan
    changed_files: list[str]


BASELINE_BLOCK = """  // Deliberately expressed as a priority chain so ChipEvolve has a focused demo target.
  always_comb begin
    y = '0;
    if (op == OP_ADD)
      y = a + b;
    else if (op == OP_SUB)
      y = a - b;
    else if (op == OP_AND)
      y = a & b;
    else if (op == OP_OR)
      y = a | b;
    else if (op == OP_XOR)
      y = a ^ b;
    else if (op == OP_SLT)
      y = {{(WIDTH-1){1'b0}}, ($signed(a) < $signed(b))};
  end"""

OPTIMIZED_BLOCK = """  // Parallel decode makes the operation intent explicit to synthesis.
  always_comb begin
    unique case (op)
      OP_ADD: y = a + b;
      OP_SUB: y = a - b;
      OP_AND: y = a & b;
      OP_OR:  y = a | b;
      OP_XOR: y = a ^ b;
      OP_SLT: y = {{(WIDTH-1){1'b0}}, ($signed(a) < $signed(b))};
      default: y = '0;
    endcase
  end"""


def plan_mux_restructure(memory_ids: list[str]) -> MutationPlan:
    return MutationPlan(
        target_module="alu",
        mutation_type="mux_restructure",
        hypothesis="The priority-chain operation decode adds avoidable mux depth; an explicit parallel case may reduce synthesized cells.",
        expected_effects={"area": "slight improvement", "power": "neutral", "performance": "possible improvement", "congestion": "neutral"},
        risk="Operation selection semantics could change for unknown control values.",
        memory_used=memory_ids,
        files_to_modify=["rtl/alu.sv"],
    )


def apply_mux_restructure(workspace: Path, plan: MutationPlan) -> MutationResult:
    target = workspace / plan.files_to_modify[0]
    source = target.read_text(encoding="utf-8")
    if BASELINE_BLOCK not in source:
        raise ValueError("Expected priority mux pattern was not found; refusing a broad rewrite.")
    target.write_text(source.replace(BASELINE_BLOCK, OPTIMIZED_BLOCK, 1), encoding="utf-8")
    return MutationResult(plan=plan, changed_files=plan.files_to_modify)

