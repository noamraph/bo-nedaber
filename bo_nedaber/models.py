from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from enum import Enum, auto
from typing import NewType

from bo_nedaber.timestamp import Timestamp


class Sex(Enum):
    MALE = auto()
    FEMALE = auto()


class Opinion(Enum):
    PRO = auto()
    CON = auto()


Uid = NewType("Uid", int)


class Cmd(Enum):
    IM_AVAILABLE_NOW = auto()
    STOP_SEARCHING = auto()


@dataclass(frozen=True)
class Msg(ABC):
    uid: Uid


@dataclass(frozen=True)
class Sched(Msg):
    """
    This is not really a message, but it's convenient to treat it is a message,
    since the list of scheduled events always comes with the list of messages.
    It means: schedule an event for user uid at the given timestamp.
    """

    ts: Timestamp


@dataclass(frozen=True)
class FoundPartner(Msg):
    other_uid: Uid


@dataclass(frozen=True)
class AreYouAvailable(Msg):
    pass


@dataclass(frozen=True)
class UserStateBase(ABC):
    uid: Uid


@dataclass(frozen=True)
class InitialState(UserStateBase):
    pass


@dataclass(frozen=True)
class WaitingForOpinion(UserStateBase):
    pass


@dataclass(frozen=True)
class WithOpinion(UserStateBase, ABC):
    sex: Sex
    opinion: Opinion


@dataclass(frozen=True)
class WaitingForPhone(WithOpinion):
    pass


@dataclass(frozen=True)
class RegisteredBase(WithOpinion, ABC):
    phone: str

    def get_inactive(self) -> Inactive:
        return Inactive(self.uid, self.sex, self.opinion, self.phone)

    def get_asking(
        self,
        searching_until: Timestamp,
        asked_uid: Uid,
        asking_until: Timestamp,
        waited_by: Uid | None,
    ) -> Asking:
        return Asking(
            self.uid,
            self.sex,
            self.opinion,
            self.phone,
            searching_until,
            asked_uid,
            asking_until,
            waited_by,
        )

    def get_waiting(
        self, searching_until: Timestamp, waiting_for: Uid | None
    ) -> Waiting:
        return Waiting(
            self.uid, self.sex, self.opinion, self.phone, searching_until, waiting_for
        )

    def get_asked(self, since: Timestamp, asked_by: Uid) -> Asked:
        return Asked(self.uid, self.sex, self.opinion, self.phone, since, asked_by)


@dataclass(frozen=True)
class Inactive(RegisteredBase):
    pass


@dataclass(frozen=True)
class Searching(RegisteredBase, ABC):
    searching_until: Timestamp


@dataclass(frozen=True)
class Asking(Searching):
    asked_uid: Uid
    asking_until: Timestamp

    # If someone is waiting for us, their uid
    waited_by: Uid | None


@dataclass(frozen=True)
class Waiting(Searching):
    """
    The user is withing a minute of being available (ie. searching), but
    not asking anyone. He may be waiting for another user who is asking.
    """

    waiting_for: Uid | None


@dataclass(frozen=True)
class Active(RegisteredBase):
    since: Timestamp


@dataclass(frozen=True)
class Asked(RegisteredBase):
    since: Timestamp
    asked_by: Uid


Registered = Inactive | Asking | Waiting | Active | Asked
UserState = InitialState | WaitingForOpinion | WaitingForPhone | Registered
