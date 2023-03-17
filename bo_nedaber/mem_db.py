from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from pqdict import pqdict

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


def get_search_score(state: UserStateBase, opinion: Opinion) -> tuple[int, int] | None:
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


@dataclass(frozen=True, order=True)
class TimestampAndUid:
    ts: Timestamp
    uid: Uid


class ReadTx(ABC):
    @abstractmethod
    def get(self, uid: Uid) -> UserState:
        ...

    @abstractmethod
    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        ...

    @abstractmethod
    def get_first_sched(self) -> UserState | None:
        ...


class Tx(ReadTx):
    @abstractmethod
    def set(self, state: UserState) -> None:
        ...


class TxContextManager(Tx):
    @abstractmethod
    def __enter__(self) -> Self:
        ...

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        ...


class DbBase(ReadTx):
    @abstractmethod
    def transaction(self) -> TxContextManager:
        ...


class MemDb(Tx, DbBase):
    def __init__(self) -> None:
        # The data
        self._states: dict[Uid, UserState] = {}
        # Sort states by get_search_score - only those with a score, of course.
        # We store two priority dicts, one for each opinion.
        self._by_score: dict[Opinion, pqdict[Uid, tuple[int, int]]] = {
            opinion: pqdict() for opinion in Opinion
        }
        # Sort states which have sched by sched.
        self._by_sched: pqdict[Uid, Timestamp] = pqdict()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemDb):
            return NotImplemented
        return self._states == other._states

    def get(self, uid: Uid) -> UserState:
        try:
            return self._states[uid]
        except KeyError:
            return InitialState(uid=uid)

    def set(self, state: UserState) -> None:
        uid = state.uid
        self._states[uid] = state

        sched = state.sched
        if sched is None:
            self._by_sched.pop(uid, None)
        else:
            self._by_sched[uid] = sched

        for opinion in Opinion:
            score = get_search_score(state, opinion)
            if score is None:
                self._by_score[opinion].pop(uid, None)
            else:
                self._by_score[opinion][uid] = score

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        """Find the highest-priority user with the given opinion"""
        if len(self._by_score[opinion]) == 0:
            return None
        uid = self._by_score[opinion].top()
        if uid is None:
            return None
        state = self._states[uid]
        assert isinstance(state, Waiting | Asking | Active)
        return state

    def get_first_sched(self) -> UserState | None:
        """Find the first scheduled state, or None if none are scheduled"""
        if len(self._by_sched) == 0:
            return None
        uid = self._by_sched.top()
        return self._states[uid]

    @contextmanager
    def transaction(self) -> TxContextManager:
        yield self