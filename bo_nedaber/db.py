from __future__ import annotations

from abc import abstractmethod
from typing import Tuple, Protocol, Self, TypeVar, Iterable, Callable

from bo_nedaber.models import (
    UserStateBase,
    Opinion,
    RegisteredBase,
    Waiting,
    Asking,
    Active,
    Uid,
    InitialState,
    UserState,
)


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


class Db:
    def __init__(self) -> None:
        self._user_state: dict[Uid, UserState] = {}

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
