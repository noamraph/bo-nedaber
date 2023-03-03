from __future__ import annotations

from bo_nedaber.bo_nedaber import (
    AskingState,
    WaitingState,
    Active,
    Inactive,
    MALE,
    FEMALE,
    PRO,
    CON,
    Timestamp,
    get_search_score,
)


def test_search() -> None:
    states = [
        Inactive(uid=1, sex=MALE, opinion=PRO, phone="1"),
        Active(uid=2, sex=FEMALE, opinion=PRO, phone="2", active_since=Timestamp(1)),
        WaitingState(
            uid=3, sex=MALE, opinion=PRO, phone="3", searching_since=Timestamp(2)
        ),
        AskingState(
            uid=4,
            sex=FEMALE,
            opinion=PRO,
            phone="4",
            searching_since=Timestamp(3),
            asked_uid=0,
            waiting_uid=None,
        ),
        AskingState(
            uid=5,
            sex=FEMALE,
            opinion=PRO,
            phone="5",
            searching_since=Timestamp(4),
            asked_uid=0,
            waiting_uid=0,
        ),
        WaitingState(
            uid=6, sex=MALE, opinion=CON, phone="6", searching_since=Timestamp(2)
        ),
    ]

    sorted_states = sorted(
        (s for s in states if get_search_score(s, PRO) is not None),
        key=lambda s: get_search_score(s, PRO),
    )
    sorted_ids = [s.uid for s in sorted_states]
    assert sorted_ids == [3, 4, 2]
