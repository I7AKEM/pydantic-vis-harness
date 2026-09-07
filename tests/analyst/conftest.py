from datetime import datetime, timezone

import pytest

from vis_agent.profiler.measurements import compute_statistics
from vis_agent.profiler.models import DatasetProfile


@pytest.fixture
def hijri(store):
    source = store.save_upload("hijri.csv", (
        "day,named_day,amount\n"
        "١٤٤٧-٠٣-١٢,١٢ ربيع الأول ١٤٤٧,١٠\n"
        "1399-12-29,29 ذو الحجة 1399,١٬٢٣٤٫٥٠\n"
        "١٤٤٧-٠٤-٠١,١ ربيع الآخر ١٤٤٧,-٥\n"
        "١٤٠٠-٠١-٠٢,٢ محرم ١٤٠٠,٢٥٫٥٠\n"
        "1447-03-22,22 ربيع الأول 1447,٢٠\n"
    ).encode())
    store.import_csv(source.dataset_id)
    statistics = compute_statistics(store, source)
    # Task 5a owns detection and the profiler's Literal; set future levels directly on this fixture.
    for column in statistics.columns:
        column.measurement_levels = ["arabic_digits"] if column.name == "amount" else ["hijri"]
    return source.dataset_id, DatasetProfile(
        source=source, status="complete", deterministic=statistics,
        created_at=datetime.now(timezone.utc),
    )
