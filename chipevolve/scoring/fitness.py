from __future__ import annotations

from chipevolve.domain.models import FitnessResult, Metrics, ObjectiveWeights, VerificationResult


OBJECTIVES: dict[str, ObjectiveWeights] = {
    "balanced": ObjectiveWeights(),
    "performance": ObjectiveWeights(power=0.20, area=0.20, delay=0.50, congestion=0.10),
    "low_power": ObjectiveWeights(power=0.55, area=0.20, delay=0.15, congestion=0.10),
    "compact": ObjectiveWeights(power=0.20, area=0.55, delay=0.15, congestion=0.10),
}


def _delay(metrics: Metrics) -> float | None:
    return 1000.0 / metrics.fmax_mhz if metrics.fmax_mhz and metrics.fmax_mhz > 0 else None


def calculate_fitness(
    baseline: Metrics,
    candidate: Metrics,
    verification: VerificationResult,
    profile: str = "balanced",
) -> FitnessResult:
    if not verification.hard_gates_passed:
        return FitnessResult(valid=False, reason="Candidate failed one or more hard verification gates.")

    weights = OBJECTIVES[profile]
    pairs = {
        "power": (baseline.power_mw, candidate.power_mw, weights.power),
        "area": (
            baseline.area_um2 or (float(baseline.cell_count) if baseline.cell_count else None),
            candidate.area_um2 or (float(candidate.cell_count) if candidate.cell_count else None),
            weights.area,
        ),
        "delay": (_delay(baseline), _delay(candidate), weights.delay),
        "congestion": (baseline.congestion, candidate.congestion, weights.congestion),
    }
    available = {key: values for key, values in pairs.items() if values[0] is not None and values[1] is not None and values[0] > 0}
    if not available:
        return FitnessResult(valid=False, reason="No comparable EDA metrics were produced; candidate cannot be scored.")

    active_weight = sum(weight for _, _, weight in available.values())
    ratios = {key: candidate_value / baseline_value for key, (baseline_value, candidate_value, _) in available.items()}
    cost = sum(ratios[key] * weight / active_weight for key, (_, _, weight) in available.items())
    improvement = (1.0 - cost) * 100.0
    return FitnessResult(
        valid=True,
        candidate_cost=cost,
        improvement_percent=improvement,
        ratios=ratios,
        reason="Candidate improves measured fitness." if cost < 1.0 else "Candidate does not improve measured fitness.",
    )
