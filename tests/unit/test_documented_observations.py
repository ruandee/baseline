from datetime import UTC, datetime
from uuid import uuid4

import pytest

from patient_memory.baseline.observations import documented_observations


@pytest.mark.parametrize("unit,value,expected", [
    ("Cel", "37.1", 37.1), ("C", "34.0", 34.0), ("\u00b0C", "37.1", 37.1),
    ("F", "98.8", None), ("Cel", "not measured", None), ("Cel", "nan", None),
])
def test_ucum_temperature_and_unknown_measurements(unit, value, expected):
    at = datetime.now(UTC)
    row = dict(id=uuid4(), source_id=uuid4(), value=value, unit=unit,
               quote=f"temperature_c: {value} {unit}", recorded_at=at, effective_at=at)

    class Connection:
        def execute(self, sql, params):
            return self

        def fetchone(self):
            return row

    result = documented_observations(Connection(), uuid4(), at, 30)
    if expected is None:
        assert result == []
    else:
        assert result[0]["value"] == expected
        assert result[0]["quote"] == row["quote"]
        assert result[0]["label"] == f"Temperature {expected:g} \u00b0C documented"
