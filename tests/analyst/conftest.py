# tests/analyst/conftest.py
from datetime import datetime, timezone

import pytest

from vis_agent.profiler.measurements import compute_statistics
from vis_agent.profiler.models import ColumnSemantics, DatasetProfile, SemanticProfile

PEOPLE = (
    b"region,gender,wealth_level,amount,day\n"
    b"East,F,Poor,10,2026-01-01\n"
    b"East,M,Rich,30,2026-01-01\n"
    b"West,F,Rich,20,2026-02-01\n"
    b"West,M,Middle,40,2026-02-01\n"
    b"West,F,Poor,5,2026-03-01\n"
)

ROLES = {"region": "geography", "gender": "category", "wealth_level": "ordinal", "amount": "measure", "day": "time"}


def semantic_profile(columns):
    return SemanticProfile(
        description="People and amounts by region.",
        row_meaning="One person.",
        columns=[
            ColumnSemantics(name=name, meaning=name, role=ROLES[name], unit="SAR" if name == "amount" else None,
                            confidence="high", evidence="fixture",
                            code_meanings={"F": "Female", "M": "Male"} if name == "gender" else None)
            for name in columns
        ],
    )


@pytest.fixture
def people(store):
    """A profiled dataset: returns (dataset_id, profile)."""
    source = store.save_upload("people.csv", PEOPLE)
    store.import_csv(source.dataset_id)
    statistics = compute_statistics(store, source)
    profile = DatasetProfile(source=source, status="complete", deterministic=statistics,
                             semantic=semantic_profile(source.headers), semantic_model="fixture",
                             created_at=datetime.now(timezone.utc))
    store.save_profile(profile)
    return source.dataset_id, profile
