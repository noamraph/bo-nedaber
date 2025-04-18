from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import Enum
from typing import NewType, get_args

from bo_nedaber.timestamp import Timestamp
from dataclasses_json import DataClassJsonMixin


class Sex(Enum):
    MALE = 0
    FEMALE = 1

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


class Opinion(Enum):
    PRO = 0
    CON = 1

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


Uid = NewType("Uid", int)


class Cmd(Enum):
    SCHED = "sched"
    MALE_PRO = "male-pro"
    MALE_CON = "male-con"
    FEMALE_PRO = "female-pro"
    FEMALE_CON = "female-con"
    IM_AVAILABLE_NOW = "im-available-now"
    STOP_SEARCHING = "stop-searching"
    IM_NO_LONGER_AVAILABLE = "im-no-longer-available"
    ANSWER_AVAILABLE = "answer-available"
    ANSWER_UNAVAILABLE = "answer-unavailable"
    S1 = "s1"
    S2 = "s2"
    S3 = "s3"
    S4 = "s4"
    S5 = "s5"
    S_DIDNT_TALK = "s-didnt-talk"
    S_NO_ANSWER = "s-no-answer"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


@dataclass(frozen=True, slots=True)
class SchedUpdate:
    """A fake update which means a scheduled event"""

    uid: Uid


#################################################
# Messages to user


@dataclass(frozen=True)
class MsgBase(ABC):
    uid: Uid


@dataclass(frozen=True)
class UnexpectedReqMsg(MsgBase):
    pass


@dataclass(frozen=True)
class WelcomeMsg(MsgBase):
    pass


@dataclass(frozen=True)
class WhatIsYourOpinionMsg(MsgBase):
    pass


@dataclass(frozen=True)
class TypeNameMsg(MsgBase):
    pass


@dataclass(frozen=True)
class RegisteredMsg(MsgBase):
    pass


@dataclass(frozen=True)
class InactiveMsg(MsgBase):
    pass


@dataclass(frozen=True)
class SearchingMsg(MsgBase):
    pass


@dataclass(frozen=True)
class UpdateSearchingMsg(MsgBase):
    seconds_left: int


@dataclass(frozen=True)
class FoundPartnerMsg(MsgBase):
    other_uid: Uid
    other_name: str
    other_sex: Sex


@dataclass(frozen=True)
class AreYouAvailableMsg(MsgBase):
    other_sex: Sex


@dataclass(frozen=True)
class AfterAskingTimedOut(MsgBase):
    pass


@dataclass(frozen=True)
class AfterReplyUnavailableMsg(MsgBase):
    pass


@dataclass(frozen=True)
class SearchTimedOutMsg(MsgBase):
    pass


@dataclass(frozen=True)
class AfterStopSearchMsg(MsgBase):
    pass


@dataclass(frozen=True)
class HowWasTheCallMsg(MsgBase):
    pass


@dataclass(frozen=True)
class ThanksForAnsweringMsg(MsgBase):
    reply: Cmd


RealMsg = (
    UnexpectedReqMsg
    | WelcomeMsg
    | WhatIsYourOpinionMsg
    | TypeNameMsg
    | RegisteredMsg
    | InactiveMsg
    | SearchingMsg
    | FoundPartnerMsg
    | AreYouAvailableMsg
    | AfterAskingTimedOut
    | AfterReplyUnavailableMsg
    | SearchTimedOutMsg
    | AfterStopSearchMsg
    | HowWasTheCallMsg
    | ThanksForAnsweringMsg
)
Msg = RealMsg | UpdateSearchingMsg


#################################################
# States


@dataclass(frozen=True)
class UserStateBase(DataClassJsonMixin, ABC):
    uid: Uid

    @property
    def sched(self) -> Timestamp | None:
        """A timestamp if an event should be triggered, or None"""
        return None


@dataclass(frozen=True)
class InitialState(UserStateBase):
    pass


@dataclass(frozen=True)
class WaitingForOpinion(UserStateBase):
    name: str


@dataclass(frozen=True)
class WithOpinionBase(UserStateBase, ABC):
    name: str
    sex: Sex
    opinion: Opinion

    def get_inactive(self, survey_ts: Timestamp | None) -> Inactive:
        return Inactive(self.uid, self.name, self.sex, self.opinion, survey_ts)

    def get_asking(
        self,
        searching_until: Timestamp,
        next_refresh: Timestamp,
        asked_uid: Uid,
        asking_until: Timestamp,
        waited_by: Uid | None,
    ) -> Asking:
        return Asking(
            self.uid,
            self.name,
            self.sex,
            self.opinion,
            searching_until,
            next_refresh,
            asked_uid,
            asking_until,
            waited_by,
        )

    def get_waiting(
        self,
        searching_until: Timestamp,
        next_refresh: Timestamp,
        waiting_for: Uid | None,
    ) -> Waiting:
        return Waiting(
            self.uid,
            self.name,
            self.sex,
            self.opinion,
            searching_until,
            next_refresh,
            waiting_for,
        )

    def get_asked(self, until: Timestamp, asked_by: Uid) -> Asked:
        return Asked(self.uid, self.name, self.sex, self.opinion, until, asked_by)

    def get_active(self, since: Timestamp) -> Active:
        return Active(self.uid, self.name, self.sex, self.opinion, since)


@dataclass(frozen=True)
class WaitingForName(WithOpinionBase):
    pass


@dataclass(frozen=True)
class Inactive(WithOpinionBase):
    # If survey_ts is not None, a survey (how was your call) is scheduled.
    survey_ts: Timestamp | None

    @property
    def sched(self) -> Timestamp | None:
        return self.survey_ts


@dataclass(frozen=True)
class SearchingBase(WithOpinionBase, ABC):
    searching_until: Timestamp
    next_refresh: Timestamp

    @property
    def sched(self) -> Timestamp | None:
        return self.next_refresh


@dataclass(frozen=True)
class Asking(SearchingBase):
    asked_uid: Uid
    asking_until: Timestamp

    # If someone is waiting for us, their uid
    waited_by: Uid | None


@dataclass(frozen=True)
class Waiting(SearchingBase):
    """
    The user is withing a minute of being available (ie. searching), but
    not asking anyone. He may be waiting for another user who is asking.
    """

    waiting_for: Uid | None


Searching = Asking | Waiting


@dataclass(frozen=True)
class Active(WithOpinionBase):
    since: Timestamp


@dataclass(frozen=True)
class Asked(WithOpinionBase):
    until: Timestamp
    asked_by: Uid

    @property
    def sched(self) -> Timestamp | None:
        return self.until


WithOpinion = WaitingForName | Inactive | Asking | Waiting | Active | Asked
UserState = InitialState | WaitingForOpinion | WithOpinion
# A mypy bug workaround
UserStateTuple = (
    InitialState,
    WaitingForOpinion,
    WaitingForName,
    Inactive,
    Asking,
    Waiting,
    Active,
    Asked,
)
assert UserStateTuple == get_args(UserState)
