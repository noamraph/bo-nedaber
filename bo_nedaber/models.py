from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import Enum, auto
from typing import NewType

from bo_nedaber.timestamp import Timestamp


class Sex(Enum):
    MALE = 0
    FEMALE = 1


class Opinion(Enum):
    PRO = 0
    CON = 1


Uid = NewType("Uid", int)


class Cmd(Enum):
    SCHED = auto()
    IM_AVAILABLE_NOW = auto()
    STOP_SEARCHING = auto()


#################################################
# Messages to user


@dataclass(frozen=True)
class MsgBase(ABC):
    state: Registered


@dataclass(frozen=True)
class Sched(MsgBase):
    # This is not really a message, but it's convenient to treat it is a message,
    # since the list of scheduled events always comes with the list of messages.
    # It means: schedule an event for user uid at the given timestamp.
    ts: Timestamp


@dataclass(frozen=True)
class UnexpectedReqMsg(MsgBase):
    pass


@dataclass(frozen=True)
class GotPhoneMsg(MsgBase):
    pass


@dataclass(frozen=True)
class SearchingMsg(MsgBase):
    pass


@dataclass(frozen=True)
class FoundPartnerMsg(MsgBase):
    other_uid: Uid
    other_name: str
    other_sex: Sex
    other_phone: str


@dataclass(frozen=True)
class AreYouAvailableMsg(MsgBase):
    other_sex: Sex


RealMsg = (
    UnexpectedReqMsg | GotPhoneMsg | SearchingMsg | FoundPartnerMsg | AreYouAvailableMsg
)
Msg = Sched | RealMsg


#################################################
# States


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
    name: str
    sex: Sex
    opinion: Opinion


@dataclass(frozen=True)
class WaitingForPhone(WithOpinion):
    pass


@dataclass(frozen=True)
class RegisteredBase(WithOpinion, ABC):
    phone: str

    def get_inactive(self) -> Inactive:
        return Inactive(self.uid, self.name, self.sex, self.opinion, self.phone)

    def get_asking(
        self,
        searching_until: Timestamp,
        asked_uid: Uid,
        asking_until: Timestamp,
        waited_by: Uid | None,
    ) -> Asking:
        return Asking(
            self.uid,
            self.name,
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
            self.uid,
            self.name,
            self.sex,
            self.opinion,
            self.phone,
            searching_until,
            waiting_for,
        )

    def get_asked(self, since: Timestamp, asked_by: Uid) -> Asked:
        return Asked(
            self.uid, self.name, self.sex, self.opinion, self.phone, since, asked_by
        )


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
