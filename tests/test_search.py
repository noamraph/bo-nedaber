from __future__ import annotations

from bo_nedaber.bo_nedaber import (
    Asking,
    Waiting,
    Active,
    Inactive,
    MALE,
    FEMALE,
    PRO,
    CON,
    get_search_score,
    Asked,
    Uid,
    Db,
)

from bo_nedaber.timestamp import Timestamp


def test_search() -> None:
    states = [
        Inactive(uid=Uid(1), sex=MALE, opinion=PRO, phone="1"),
        Active(uid=Uid(2), sex=FEMALE, opinion=PRO, phone="2", since=Timestamp(1)),
        Waiting(
            uid=Uid(3),
            sex=MALE,
            opinion=PRO,
            phone="3",
            since=Timestamp(2),
            waiting_for=Uid(10),
        ),
        Asking(
            uid=Uid(4),
            sex=FEMALE,
            opinion=PRO,
            phone="4",
            since=Timestamp(3),
            asked_uid=Uid(0),
            waiting_uid=None,
        ),
        Asking(
            uid=Uid(5),
            sex=FEMALE,
            opinion=PRO,
            phone="5",
            since=Timestamp(4),
            asked_uid=Uid(0),
            waiting_uid=Uid(0),
        ),
        Waiting(
            uid=Uid(6),
            sex=MALE,
            opinion=CON,
            phone="6",
            since=Timestamp(2),
            waiting_for=Uid(10),
        ),
    ]

    sorted_states = sorted(
        (s for s in states if get_search_score(s, PRO) is not None),
        key=lambda s: get_search_score(s, PRO),  # type: ignore[arg-type, return-value]
    )
    sorted_ids = [s.uid for s in sorted_states]
    assert sorted_ids == [Uid(3), Uid(4), Uid(2)]


def test_simple_search() -> None:
    # U2 is waiting.
    # U1 is inactive.
    # Event: U1 starts searching.
    #
    # Expected messages:
    # U1 and U2 get a "you can talk" message.
    #
    # Expected final state:
    # U1 and U2 are inactive.
    pass


def test_4_updates() -> None:
    # U1 asked U2.
    # U3 is waiting to see if U1 will be declined.
    # U4 is active.
    # Event: U2 accepted U1.
    #
    # Expected messages:
    # U1 and U2 get a "you can talk" message with the details of the other.
    # U3 doesn't get a message, since the search continues.
    # U4 gets a "are you available" message.
    #
    # Expected final state:
    # U1 and U2 are inactive.
    # U3 is in Waiting state.
    # U4 if is Asked state.
    before_states = [
        Asking(
            uid=Uid(1),
            sex=MALE,
            opinion=PRO,
            phone="1",
            since=Timestamp(1),
            asked_uid=Uid(2),
            waiting_uid=Uid(3),
        ),
        Asked(uid=Uid(2), sex=MALE, opinion=CON, phone="2", since=Timestamp(0)),
        Waiting(
            uid=Uid(3),
            sex=MALE,
            opinion=CON,
            phone="3",
            since=Timestamp(2),
            waiting_for=Uid(1),
        ),
        Active(uid=Uid(4), sex=MALE, opinion=PRO, phone="4", since=Timestamp(-1)),
    ]

    expected_after_states = [
        Inactive(uid=Uid(1), sex=MALE, opinion=PRO, phone="1"),
        Inactive(uid=Uid(2), sex=MALE, opinion=CON, phone="2"),
        Waiting(
            uid=Uid(3),
            sex=MALE,
            opinion=CON,
            phone="3",
            since=Timestamp(2),
            waiting_for=Uid(4),
        ),
        Asked(uid=Uid(4), sex=MALE, opinion=PRO, phone="4", since=Timestamp(10)),
    ]

    db = Db()
    for state in before_states:
        db.set(state)
