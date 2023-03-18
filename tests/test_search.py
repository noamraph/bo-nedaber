from __future__ import annotations

import random

from bo_nedaber.bo_nedaber import (
    ASKING_DURATION,
    CON,
    MALE,
    PRO,
    SEARCH_UPDATE_INTERVAL,
    SURVEY_DURATION,
    handle_cmd,
)
from bo_nedaber.mem_db import MemDb, get_search_score
from bo_nedaber.models import (
    Active,
    AfterAskingTimedOut,
    AfterReplyUnavailableMsg,
    AreYouAvailableMsg,
    Asked,
    Asking,
    Cmd,
    FoundPartnerMsg,
    Inactive,
    Opinion,
    SearchTimedOutMsg,
    Uid,
    UserState,
    Waiting,
)
from bo_nedaber.timestamp import Duration, Timestamp

#################################
# Uninteresting helper functions


def inactive(n: int, opinion: Opinion, survey_ts: Timestamp | None) -> Inactive:
    return Inactive(Uid(n), str(n), MALE, opinion, str(n), survey_ts)


def asking(
    n: int,
    opinion: Opinion,
    searching_until: Timestamp,
    next_refresh: Timestamp,
    asked_uid: Uid,
    asking_until: Timestamp,
    waited_by: Uid | None,
) -> Asking:
    return Asking(
        Uid(n),
        str(n),
        MALE,
        opinion,
        str(n),
        searching_until,
        next_refresh,
        asked_uid,
        asking_until,
        waited_by,
    )


def waiting(
    n: int,
    opinion: Opinion,
    searching_until: Timestamp,
    next_refresh: Timestamp,
    waiting_for: Uid | None,
) -> Waiting:
    return Waiting(
        Uid(n),
        str(n),
        MALE,
        opinion,
        str(n),
        searching_until,
        next_refresh,
        waiting_for,
    )


def asked(n: int, opinion: Opinion, until: Timestamp, asked_by: Uid) -> Asked:
    return Asked(Uid(n), str(n), MALE, opinion, str(n), until, asked_by)


def active(n: int, opinion: Opinion, since: Timestamp) -> Active:
    return Active(Uid(n), str(n), MALE, opinion, str(n), since)


def found_partner(n: int, other_n: int) -> FoundPartnerMsg:
    # Shortcut function
    return FoundPartnerMsg(
        Uid(n),
        other_uid=Uid(other_n),
        other_name=str(other_n),
        other_sex=MALE,
        other_phone=str(other_n),
    )


###############
# Actual tests


def test_search_priority() -> None:
    states = [
        inactive(1, PRO, None),
        active(2, PRO, since=Timestamp(1)),
        active(3, PRO, since=Timestamp(2)),
        waiting(
            4,
            PRO,
            searching_until=Timestamp(2),
            next_refresh=Timestamp(0),
            waiting_for=Uid(10),
        ),
        waiting(
            5,
            PRO,
            searching_until=Timestamp(3),
            next_refresh=Timestamp(0),
            waiting_for=None,
        ),
        asking(
            6,
            PRO,
            searching_until=Timestamp(13),
            next_refresh=Timestamp(0),
            asking_until=Timestamp(2),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        asking(
            7,
            PRO,
            searching_until=Timestamp(12),
            next_refresh=Timestamp(0),
            asking_until=Timestamp(3),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        # Should not be included because waited_by is not None
        asking(
            8,
            PRO,
            searching_until=Timestamp(10),
            next_refresh=Timestamp(0),
            asking_until=Timestamp(10),
            asked_uid=Uid(0),
            waited_by=Uid(0),
        ),
        # Should not be included because of opinion
        waiting(
            9,
            CON,
            searching_until=Timestamp(10),
            next_refresh=Timestamp(0),
            waiting_for=Uid(10),
        ),
    ]

    for i in range(10):
        random.shuffle(states)
        sorted_states = sorted(
            (s for s in states if get_search_score(s, PRO) is not None),
            key=lambda s: get_search_score(s, PRO),  # type: ignore[arg-type, return-value]
        )
        assert [s.uid for s in sorted_states] == [4, 5, 6, 7, 3, 2]


def get_db(*states: UserState) -> MemDb:
    db = MemDb()
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
    cur_ts = Timestamp(0)

    u1 = inactive(1, PRO, None)
    u2 = waiting(
        2,
        CON,
        searching_until=Timestamp(10),
        next_refresh=Timestamp(5),
        waiting_for=None,
    )

    emsgs = {found_partner(1, 2), found_partner(2, 1)}

    e1 = inactive(1, PRO, cur_ts + SURVEY_DURATION)
    e2 = inactive(2, CON, cur_ts + SURVEY_DURATION)

    db = get_db(u1, u2)
    msgs = handle_cmd(u1, db, Timestamp(0), Cmd.IM_AVAILABLE_NOW)
    assert set(msgs) == emsgs
    assert db == get_db(e1, e2)


def test_reply_available() -> None:
    # U1 asked U2
    # Event: U2 accepted.
    # Expected messages:
    # U1 and U2 get a "found partner" message with the details of the other.
    # Expected final state:
    # U1 and U2 are inactive.
    cur_ts = Timestamp(10)
    u1 = asking(
        1,
        PRO,
        searching_until=Timestamp(10),
        next_refresh=Timestamp(10),
        asked_uid=Uid(2),
        asking_until=Timestamp(5),
        waited_by=None,
    )
    u2 = asked(2, CON, until=Timestamp(5), asked_by=Uid(1))

    emsgs = {
        found_partner(1, 2),
        found_partner(2, 1),
    }

    e1 = inactive(1, PRO, cur_ts + SURVEY_DURATION)
    e2 = inactive(2, CON, cur_ts + SURVEY_DURATION)

    db = get_db(u1, u2)
    msgs = handle_cmd(u2, db, cur_ts, Cmd.ANSWER_AVAILABLE)
    assert set(msgs) == emsgs
    assert db == get_db(e1, e2)


def test_reply_unavailable() -> None:
    # U1 asked U2
    # U3 is active
    # Event: U2 rejected.
    # Expected messages:
    # U2 gets a AfterReplyUnavailableMsg
    # U3 gets AreYouAvailableMsg
    # Expected final state:
    # U1 is in asking state, U2 is inactive, U3 is asked

    cur_ts = Timestamp(10)
    u1 = asking(
        1,
        PRO,
        searching_until=cur_ts + ASKING_DURATION + Duration(1),
        next_refresh=cur_ts + Duration(3),
        asked_uid=Uid(2),
        asking_until=cur_ts + Duration(5),
        waited_by=None,
    )
    u2 = asked(2, CON, until=u1.asking_until, asked_by=Uid(1))
    u3 = active(3, CON, since=Timestamp(0))

    emsgs = {AfterReplyUnavailableMsg(Uid(2)), AreYouAvailableMsg(Uid(3), MALE)}

    e1 = asking(
        1,
        PRO,
        u1.searching_until,
        u1.next_refresh,
        asked_uid=Uid(3),
        asking_until=cur_ts + ASKING_DURATION,
        waited_by=None,
    )
    e2 = inactive(2, CON, None)
    e3 = asked(3, CON, cur_ts + ASKING_DURATION, Uid(1))

    db = get_db(u1, u2, u3)
    msgs = handle_cmd(u2, db, cur_ts, Cmd.ANSWER_UNAVAILABLE)
    assert set(msgs) == emsgs
    assert db._states == get_db(e1, e2, e3)._states


def test_search_timeout() -> None:
    # U1 asked U2
    # U3 is waiting for U1
    # U4 is waiting
    # Event: U1 search timed out
    # Expected messages:
    # U1 gets SearchTimedOutMsg
    # U2 gets a AfterAskingTimedOut
    # U3 and U4 get FoundPartnerMsg
    # Expected final state:
    # U1 is in active state, U2 is inactive, U3 and U4 are inactive (with survey scheduled)

    cur_ts = Timestamp(10)
    u1 = asking(
        1,
        PRO,
        searching_until=cur_ts,
        next_refresh=cur_ts,
        asked_uid=Uid(2),
        asking_until=cur_ts + Duration(5),
        waited_by=Uid(3),
    )
    u2 = asked(2, CON, until=u1.asking_until, asked_by=Uid(1))
    u3 = waiting(
        3,
        CON,
        searching_until=cur_ts + Duration(1),
        next_refresh=cur_ts + Duration(1),
        waiting_for=Uid(1),
    )
    u4 = waiting(
        4,
        PRO,
        searching_until=u3.searching_until,
        next_refresh=cur_ts + Duration(2),
        waiting_for=None,
    )

    emsgs = {
        SearchTimedOutMsg(Uid(1)),
        AfterAskingTimedOut(Uid(2)),
        FoundPartnerMsg(Uid(3), Uid(4), "4", MALE, "4"),
        FoundPartnerMsg(Uid(4), Uid(3), "3", MALE, "3"),
    }

    e1 = active(1, PRO, cur_ts)
    e2 = inactive(2, CON, None)
    e3 = inactive(3, CON, cur_ts + SURVEY_DURATION)
    e4 = inactive(4, PRO, cur_ts + SURVEY_DURATION)

    db = get_db(u1, u2, u3, u4)
    msgs = handle_cmd(u1, db, cur_ts, Cmd.SCHED)
    assert set(msgs) == emsgs
    assert db._states == get_db(e1, e2, e3, e4)._states


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
    u1 = asking(
        1,
        PRO,
        searching_until=Timestamp(10),
        next_refresh=Timestamp(10),
        asked_uid=Uid(2),
        asking_until=Timestamp(5),
        waited_by=Uid(3),
    )
    u2 = asked(2, CON, until=Timestamp(5), asked_by=Uid(1))
    u3 = waiting(
        3,
        CON,
        searching_until=cur_ts + ASKING_DURATION + Duration(1),
        next_refresh=cur_ts + SEARCH_UPDATE_INTERVAL,
        waiting_for=Uid(1),
    )
    u4 = active(4, PRO, since=Timestamp(-1))

    emsgs = {
        found_partner(1, 2),
        found_partner(2, 1),
        AreYouAvailableMsg(Uid(4), MALE),
    }

    e1 = inactive(1, PRO, cur_ts + SURVEY_DURATION)
    e2 = inactive(2, CON, cur_ts + SURVEY_DURATION)
    e3 = asking(
        3,
        CON,
        searching_until=u3.searching_until,
        next_refresh=u3.next_refresh,
        asked_uid=Uid(4),
        asking_until=cur_ts + ASKING_DURATION,
        waited_by=None,
    )
    e4 = asked(4, PRO, until=cur_ts + ASKING_DURATION, asked_by=Uid(3))

    db = get_db(u1, u2, u3, u4)
    msgs = handle_cmd(u2, db, cur_ts, Cmd.ANSWER_AVAILABLE)
    assert set(msgs) == emsgs
    assert db == get_db(e1, e2, e3, e4)
