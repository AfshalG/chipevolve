from chipevolve.domain.models import Metrics
from chipevolve.storage.repository import Repository


def test_metrics_round_trip(tmp_path) -> None:
    repository = Repository(tmp_path / "state.sqlite3")
    repository.set_metrics("baseline", Metrics(cell_count=42))
    assert repository.get_metrics("baseline") == Metrics(cell_count=42)
