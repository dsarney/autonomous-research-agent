from app.models import ResearchRun
from app.store import RunStore


def test_save_does_not_revive_a_cancelled_run() -> None:
    store = RunStore()
    store.save(ResearchRun(id="run-9", query="stop overwrite please", status="running"))
    store.save(ResearchRun(id="run-9", query="stop overwrite please", status="cancelled"))
    saved = store.save(
        ResearchRun(id="run-9", query="stop overwrite please", status="complete")
    )
    assert saved.status == "cancelled"
    assert store.get("run-9") is not None
    assert store.get("run-9").status == "cancelled"
