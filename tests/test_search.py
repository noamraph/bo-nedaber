from __future__ import annotations

import random
from typing import Any, TypeVar

from bo_nedaber.bo_nedaber import CON, MALE, PRO, handle_cmd, ASKING_DURATION
from bo_nedaber.db import Db, get_search_score
from bo_nedaber.models import (
    Active,
    Asked,
    Asking,
    Inactive,
    Uid,
    Waiting,
    Registered,
    Opinion,
    FoundPartnerMsg,
    UserState,
    Cmd,
    AreYouAvailableMsg,
    Sched,
)
from bo_nedaber.timestamp import Timestamp, Duration


T = TypeVar("T", bound=Registered)


def st(state: type[T], n: int, opinion: Opinion, **kwargs: Any) -> T:
    # Shortcut function
    r = state(Uid(n), name=str(n), sex=MALE, opinion=opinion, phone=str(n), **kwargs)
    assert isinstance(r, state)  # for mypy
    return r


def found_partner(n: int, other_n: int) -> FoundPartnerMsg:
    # Shortcut function
    return FoundPartnerMsg(
        Uid(n),
        other_uid=Uid(other_n),
        other_name=str(other_n),
        other_sex=MALE,
        other_phone=str(other_n),
    )


def test_search_priority() -> None:
    states = [
        st(Inactive, 1, PRO),
        st(Active, 2, PRO, since=Timestamp(1)),
        st(Active, 3, PRO, since=Timestamp(2)),
        st(Waiting, 4, PRO, searching_until=Timestamp(2), waiting_for=Uid(10)),
        st(Waiting, 5, PRO, searching_until=Timestamp(3), waiting_for=None),
        st(
            Asking,
            6,
            PRO,
            searching_until=Timestamp(13),
            asking_until=Timestamp(2),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        st(
            Asking,
            7,
            PRO,
            searching_until=Timestamp(12),
            asking_until=Timestamp(3),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        # Should not be included because waited_by is not None
        st(
            Asking,
            8,
            PRO,
            searching_until=Timestamp(10),
            asking_until=Timestamp(10),
            asked_uid=Uid(0),
            waited_by=Uid(0),
        ),
        # Should not be included because of opinion
        st(Waiting, 9, CON, searching_until=Timestamp(10), waiting_for=Uid(10)),
    ]

    for i in range(10):
        random.shuffle(states)
        sorted_states = sorted(
            (s for s in states if get_search_score(s, PRO) is not None),
            key=lambda s: get_search_score(s, PRO),  # type: ignore[arg-type, return-value]
        )
        assert [s.uid for s in sorted_states] == [4, 5, 6, 7, 3, 2]


def get_db(*states: UserState) -> Db:
    db = Db()
    for state in states:
        db.set(state)
    return db


def test_simple_search() -> None:
    # U2 is waiting.
    # U1 is inactive.
    # Event: U1 starts searching.
    #
    # Expected messages:
    # U1 and U2 get a "found partner" message.
    #
    # Expected final state:
    # U1 and U2 are inactive.
    u1 = st(Inactive, 1, PRO)
    u2 = st(Waiting, 2, CON, searching_until=Timestamp(10), waiting_for=None)

    emsgs = {found_partner(1, 2), found_partner(2, 1)}

    e1 = st(Inactive, 1, PRO)
    e2 = st(Inactive, 2, CON)

    db = get_db(u1, u2)
    msgs = handle_cmd(u1, db, Timestamp(0), Cmd.IM_AVAILABLE_NOW)
    assert set(msgs) == emsgs
    assert db == get_db(e1, e2)


def test_4_updates() -> None:
    # U1 asked U2.
    # U3 is waiting to see if U1 will be declined.
    # U4 is active.
    # Event: U2 accepted U1.
    #
    # Expected messages:
    # U1 and U2 get a "found partner" message with the details of the other.
    # U3 doesn't get a message, since the search continues.
    # U4 gets a "are you available" message.
    #
    # Expected final state:
    # U1 and U2 are inactive.
    # U3 is in Asking state.
    # U4 if is Asked state.
    cur_ts = Timestamp(10)
    u1 = st(
        Asking,
        1,
        PRO,
        searching_until=Timestamp(10),
        asked_uid=Uid(2),
        asking_until=Timestamp(5),
        waited_by=Uid(3),
    )
    u2 = st(Asked, 2, CON, since=Timestamp(0), asked_by=Uid(1))
    u3 = st(
        Waiting,
        3,
        CON,
        searching_until=cur_ts + ASKING_DURATION + Duration(1),
        waiting_for=Uid(1),
    )
    u4 = st(Active, 4, PRO, since=Timestamp(-1))

    emsgs = {
        found_partner(1, 2),
        found_partner(2, 1),
        AreYouAvailableMsg(Uid(4), MALE),
        Sched(Uid(4), cur_ts + ASKING_DURATION),
    }

    e1 = st(Inactive, 1, PRO)
    e2 = st(Inactive, 2, CON)
    e3 = st(
        Asking,
        3,
        CON,
        searching_until=u3.searching_until,
        asked_uid=Uid(4),
        asking_until=cur_ts + ASKING_DURATION,
        waited_by=None,
    )
    e4 = st(Asked, 4, PRO, since=cur_ts, asked_by=Uid(3))

    db = get_db(u1, u2, u3, u4)
    msgs = handle_cmd(u2, db, cur_ts, Cmd.ANSWER_AVAILABLE)
    assert set(msgs) == emsgs
    assert db == get_db(e1, e2, e3, e4)
