from __future__ import annotations

import random

from bo_nedaber.bo_nedaber import (
    CON,
    FEMALE,
    MALE,
    PRO,
)
from bo_nedaber.db import get_search_score, Db
from bo_nedaber.models import Inactive, Asking, Waiting, Active, Asked, Uid
from bo_nedaber.timestamp import Timestamp


def test_search_priority() -> None:
    states = [
        Inactive(uid=Uid(1), sex=MALE, opinion=PRO, phone="1"),
        Active(uid=Uid(2), sex=FEMALE, opinion=PRO, phone="2", since=Timestamp(1)),
        Active(uid=Uid(3), sex=FEMALE, opinion=PRO, phone="2", since=Timestamp(2)),
        Waiting(
            uid=Uid(4),
            sex=MALE,
            opinion=PRO,
            phone="4",
            searching_until=Timestamp(2),
            waiting_for=Uid(10),
        ),
        Waiting(
            uid=Uid(5),
            sex=MALE,
            opinion=PRO,
            phone="5",
            searching_until=Timestamp(3),
            waiting_for=None,
        ),
        Asking(
            uid=Uid(6),
            sex=FEMALE,
            opinion=PRO,
            phone="6",
            searching_until=Timestamp(13),
            asking_until=Timestamp(2),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        Asking(
            uid=Uid(7),
            sex=FEMALE,
            opinion=PRO,
            phone="7",
            searching_until=Timestamp(12),
            asking_until=Timestamp(3),
            asked_uid=Uid(0),
            waited_by=None,
        ),
        # Should not be included because waited_by is not None
        Asking(
            uid=Uid(8),
            sex=FEMALE,
            opinion=PRO,
            phone="8",
            searching_until=Timestamp(10),
            asking_until=Timestamp(10),
            asked_uid=Uid(0),
            waited_by=Uid(0),
        ),
        # Should not be included because of opinion
        Waiting(
            uid=Uid(9),
            sex=MALE,
            opinion=CON,
            phone="9",
            searching_until=Timestamp(10),
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


# def test_4_updates() -> None:
#     # U1 asked U2.
#     # U3 is waiting to see if U1 will be declined.
#     # U4 is active.
#     # Event: U2 accepted U1.
#     #
#     # Expected messages:
#     # U1 and U2 get a "you can talk" message with the details of the other.
#     # U3 doesn't get a message, since the search continues.
#     # U4 gets a "are you available" message.
#     #
#     # Expected final state:
#     # U1 and U2 are inactive.
#     # U3 is in Asking state.
#     # U4 if is Asked state.
#     before_states = [
#         Asking(
#             uid=Uid(1),
#             sex=MALE,
#             opinion=PRO,
#             phone="1",
#             searching_until=Timestamp(10),
#             asked_uid=Uid(2),
#             asking_until=Timestamp(5),
#             waited_by=Uid(3),
#         ),
#         Asked(
#             uid=Uid(2),
#             sex=MALE,
#             opinion=CON,
#             phone="2",
#             since=Timestamp(0),
#             asked_by=Uid(1),
#         ),
#         Waiting(
#             uid=Uid(3),
#             sex=MALE,
#             opinion=CON,
#             phone="3",
#             since=Timestamp(2),
#             waiting_for=Uid(1),
#         ),
#         Active(uid=Uid(4), sex=MALE, opinion=PRO, phone="4", since=Timestamp(-1)),
#     ]
#
#     expected_after_states = [
#         Inactive(uid=Uid(1), sex=MALE, opinion=PRO, phone="1"),
#         Inactive(uid=Uid(2), sex=MALE, opinion=CON, phone="2"),
#         Asking(
#             uid=Uid(3),
#             sex=MALE,
#             opinion=CON,
#             phone="3",
#             since=Timestamp(2),
#             asked_uid=Uid(4),
#             waited_by=None,
#         ),
#         Asked(
#             uid=Uid(4),
#             sex=MALE,
#             opinion=PRO,
#             phone="4",
#             since=Timestamp(10),
#             asked_by=Uid(3),
#         ),
#     ]
#
#     db = Db()
#     for state in before_states:
#         db.set(state)
