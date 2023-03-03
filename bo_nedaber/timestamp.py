from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Type, assert_never, overload


@dataclass(frozen=True, slots=True, order=True)
class Timestamp:
    seconds: int

    def __init__(self, seconds_or_str: int | str | Timestamp, /):
        match seconds_or_str:
            case Timestamp(seconds):
                object.__setattr__(self, "seconds", seconds)
            case int(seconds):
                object.__setattr__(self, "seconds", seconds)
            case str(s):
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    raise ValueError("Only accepts dates with timezone")
                if dt.microsecond != 0:
                    raise ValueError("Only accepts integer number of seconds")
                object.__setattr__(self, "seconds", int(dt.timestamp()))
            case _:
                assert_never(seconds_or_str)

    def __repr__(self) -> str:
        dt = datetime.fromtimestamp(self.seconds, timezone.utc)
        s = dt.isoformat(" ").replace("+00:00", "Z")
        return f"{self.__class__.__name__}({s!r})"

    @classmethod
    def __get_validators__(cls) -> Iterator[Type[Timestamp]]:
        yield cls

    @overload
    def __sub__(self, other: Timestamp) -> Duration:
        ...

    @overload
    def __sub__(self, other: Duration) -> Timestamp:
        ...

    def __sub__(self, other: Timestamp | Duration) -> Duration | Timestamp:
        match other:
            case Timestamp(seconds):
                return Duration(self.seconds - seconds)
            case Duration(seconds):
                return Timestamp(self.seconds - seconds)
            case _:
                assert_never(other)

    def __add__(self, other: Duration) -> Timestamp:
        return Timestamp(self.seconds + other.seconds)


@dataclass(frozen=True, slots=True, order=True)
class Duration:
    seconds: int

    @overload
    def __add__(self, other: Timestamp) -> Timestamp:
        ...

    @overload
    def __add__(self, other: Duration) -> Duration:
        ...

    def __add__(self, other: Timestamp | Duration) -> Duration | Timestamp:
        match other:
            case Timestamp(seconds):
                return Timestamp(self.seconds + seconds)
            case Duration(seconds):
                return Duration(self.seconds + seconds)
            case _:
                assert_never(other)

    def __sub__(self, other: Duration) -> Duration:
        return Duration(self.seconds - other.seconds)

    def __neg__(self) -> Duration:
        return Duration(-self.seconds)
