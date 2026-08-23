from chipevolve.domain.models import Metrics, VerificationResult
from chipevolve.scoring.fitness import calculate_fitness


def passing_verification() -> VerificationResult:
    return VerificationResult(
        protected_files_intact=True,
        lint_passed=True,
        simulation_passed=True,
        synthesis_passed=True,
    )


def test_cell_count_proxy_scores_real_available_metric() -> None:
    result = calculate_fitness(Metrics(cell_count=100), Metrics(cell_count=90), passing_verification())
    assert result.valid
    assert result.candidate_cost == 0.9
    assert result.improvement_percent == pytest.approx(10.0)


def test_missing_metrics_cannot_be_accepted() -> None:
    result = calculate_fitness(Metrics(), Metrics(), passing_verification())
    assert not result.valid
    assert "No comparable" in result.reason


def test_failed_hard_gate_rejects_even_when_area_improves() -> None:
    verification = passing_verification()
    verification.simulation_passed = False
    result = calculate_fitness(Metrics(cell_count=100), Metrics(cell_count=50), verification)
    assert not result.valid


import pytest

