from __future__ import annotations

import pytest
from pydantic import BaseModel

from bo_nedaber.timestamp import Duration, Timestamp


def test_timestamp() -> None:
    ts = Timestamp(5)
    assert repr(ts) == "Timestamp('1970-01-01 00:00:05Z')"
    assert ts == Timestamp("1970-01-01 00:00:05Z")
    assert ts > Timestamp("1970-01-01 00:10:00+0200")
    assert ts + Duration(8) == Timestamp(13)
    assert Timestamp("2023-02-27 21:41Z") - Timestamp(
        "2023-02-26 23:41+0200"
    ) == Duration(86400)
    assert Duration(8) - Duration(2) == Duration(6)
    assert Duration(8) + Duration(3) == Duration(11)
    assert Duration(8) + Timestamp(5) == Timestamp(13)
    assert Duration(8) < Duration(9)


def test_bad_constructors() -> None:
    with pytest.raises(Exception):
        # noinspection PyTypeChecker
        Timestamp(5.5)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        Timestamp("1970-01-01 00:00:05")

    with pytest.raises(ValueError):
        Timestamp("1970-01-01 00:00:05.2Z")


def test_pydantic() -> None:
    class MyModel(BaseModel):
        ts: Timestamp

        class Config:
            json_encoders = {
                Timestamp: lambda ts: ts.seconds,
            }

    raw = '{"ts": 100}'
    obj = MyModel(ts=Timestamp("1970-01-01 00:01:40Z"))

    assert MyModel.parse_raw(raw) == obj
    assert obj.json() == raw
