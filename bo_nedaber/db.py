from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, Self, Tuple, TypeVar

from bo_nedaber.models import (
    Active,
    Asking,
    InitialState,
    Opinion,
    RegisteredBase,
    Uid,
    UserState,
    UserStateBase,
    Waiting,
)
from bo_nedaber.timestamp import Timestamp


def get_search_score(state: UserStateBase, opinion: Opinion) -> Tuple[int, int] | None:
    """Return the priority for who should we connect to.
    Lower order means higher priority."""
    if not isinstance(state, RegisteredBase):
        return None
    if state.opinion != opinion:
        return None
    if isinstance(state, Waiting):
        return 1, state.searching_until.seconds
    elif isinstance(state, Asking) and state.waited_by is None:
        return 2, state.asking_until.seconds
    elif isinstance(state, Active):
        return 3, -state.since.seconds
    else:
        return None


class Comparable(Protocol):
    @abstractmethod
    def __lt__(self, other: Self) -> bool:
        ...


T = TypeVar("T")
S = TypeVar("S", bound=Comparable)


def min_if(iterable: Iterable[T], *, key: Callable[[T], S | None]) -> T | None:
    best: T | None = None
    best_score: S | None = None
    for x in iterable:
        score = key(x)
        if score is not None:
            if best_score is None or score < best_score:
                best = x
                best_score = score
    return best


@dataclass(frozen=True, order=True)
class TimestampAndUid:
    ts: Timestamp
    uid: Uid


class Db:
    def __init__(self) -> None:
        self._user_state: dict[Uid, UserState] = {}
        self._message_ids: dict[Uid, int] = {}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Db):
            return NotImplemented
        return (self._user_state, self._message_ids) == (
            other._user_state,
            other._message_ids,
        )

    def get(self, uid: Uid) -> UserState:
        try:
            return self._user_state[uid]
        except KeyError:
            return InitialState(uid=uid)

    def set(self, state: UserState) -> None:
        self._user_state[state.uid] = state

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        r = min_if(
            self._user_state.values(),
            key=lambda state: get_search_score(state, opinion),
        )
        assert isinstance(r, Waiting | Asking | Active | type(None))
        return r

    def get_events(self, ts: Timestamp) -> Iterable[UserState]:
        """
        Yield all events up to the given timestamp
        """

        def get_sched(st: UserState) -> Timestamp:
            sched = st.sched
            assert sched is not None
            return sched

        return sorted(
            (
                state
                for state in self._user_state.values()
                if state.sched is not None and state.sched <= ts
            ),
            key=get_sched,
        )

    def get_next_ts(self) -> Timestamp | None:
        state = min_if(self._user_state.values(), key=lambda st: st.sched)
        return state.sched if state is not None else None

    def set_message_id(self, uid: Uid, message_id: int) -> None:
        self._message_ids[uid] = message_id

    def get_message_id(self, uid: Uid) -> int | None:
        return self._message_ids.get(uid)
