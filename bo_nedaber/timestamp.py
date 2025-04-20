from __future__ import annotations

from datetime import datetime, timezone
from functools import total_ordering
from typing import assert_never, overload

from pydantic import BaseModel, model_serializer, model_validator


@total_ordering
class Timestamp(BaseModel):
    seconds: int

    def __init__(self, seconds: int | str | Timestamp):
        if isinstance(seconds, int):
            s = seconds
        elif isinstance(seconds, str):
            dt = datetime.fromisoformat(seconds)
            if dt.tzinfo is None:
                raise ValueError("Only accepts dates with timezone")
            if dt.microsecond != 0:
                raise ValueError("Only accepts integer number of seconds")
            s = int(dt.timestamp())
        elif isinstance(seconds, Timestamp):
            s = seconds.seconds
        else:
            assert_never(seconds)
        super().__init__(seconds=s)

    @model_serializer
    def ser_model(self) -> int:
        return self.seconds

    @model_validator(mode="before")
    @classmethod
    def validate_model(cls, data: object) -> object:
        if isinstance(data, int):
            return dict(seconds=data)
        else:
            return data

    @staticmethod
    def now() -> Timestamp:
        return Timestamp(seconds=int(datetime.now().timestamp()))

    def __repr__(self) -> str:
        dt = datetime.fromtimestamp(self.seconds, timezone.utc)
        s = dt.isoformat(" ").replace("+00:00", "Z")
        return f"{self.__class__.__name__}({s!r})"

    @overload
    def __sub__(self, other: Timestamp) -> Duration:
        ...

    @overload
    def __sub__(self, other: Duration) -> Timestamp:
        ...

    def __sub__(self, other: Timestamp | Duration) -> Duration | Timestamp:
        if isinstance(other, Timestamp):
            return Duration(seconds=self.seconds - other.seconds)
        elif isinstance(other, Duration):
            return Timestamp(seconds=self.seconds - other.seconds)
        else:
            assert_never(other)

    def __add__(self, other: Duration) -> Timestamp:
        return Timestamp(seconds=self.seconds + other.seconds)

    def __lt__(self, other: Timestamp) -> bool:
        return self.seconds < other.seconds


@total_ordering
class Duration(BaseModel):
    seconds: int

    def __init__(self, seconds: int):
        super().__init__(seconds=seconds)

    @overload
    def __add__(self, other: Timestamp) -> Timestamp:
        ...

    @overload
    def __add__(self, other: Duration) -> Duration:
        ...

    def __add__(self, other: Timestamp | Duration) -> Duration | Timestamp:
        if isinstance(other, Timestamp):
            return Timestamp(seconds=self.seconds + other.seconds)
        elif isinstance(other, Duration):
            return Duration(seconds=self.seconds + other.seconds)
        else:
            assert_never(other)

    def __sub__(self, other: Duration) -> Duration:
        return Duration(seconds=self.seconds - other.seconds)

    def __neg__(self) -> Duration:
        return Duration(seconds=-self.seconds)

    def __lt__(self, other: Duration) -> bool:
        return self.seconds < other.seconds
