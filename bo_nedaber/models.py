from __future__ import annotations

from abc import ABC, abstractmethod
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
    state: WithOpinion


@dataclass(frozen=True)
class Sched(MsgBase):
    """
    This is not really a message, but it's convenient to treat it is a message,
    since the list of scheduled events always comes with the list of messages.
    It means: schedule an event for user uid at the given timestamp.
    """

    ts: Timestamp


@dataclass(frozen=True)
class RealMsg(MsgBase, ABC):
    @abstractmethod
    def format(self) -> str:
        ...

    @abstractmethod
    def cmds(self) -> list[Cmd]:
        ...


Msg = Sched | RealMsg


@dataclass(frozen=True)
class UnexpectedReqMsg(RealMsg):
    def format(self) -> str:
        return "אני מצטער, לא הבנתי. תוכל[/י] ללחוץ על אחת התגובות המוכנות מראש?"

    def cmds(self) -> list[Cmd]:
        return []


@dataclass(frozen=True)
class GotPhoneMsg(RealMsg):
    def format(self) -> str:
        return """
תודה, רשמתי את מספר הטלפון שלך. תופיע[/י] כך: {}, [תומך/תומכת|מתנגד/מתנגדת], {}.

האם את[ה/] פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך]?

כשתלח[ץ/צי] על הכפתור, אחפש [מתנגד|תומך] שפנוי לשיחה עכשיו.
אם אמצא, אעביר לו את המספר שלך, ולך את המספר שלו.
"""

    def cmds(self) -> list[Cmd]:
        return [Cmd.IM_AVAILABLE_NOW]


@dataclass(frozen=True)
class SearchingMsg(RealMsg):
    def format(self) -> str:
        return """
מחפש...
"""

    def cmds(self) -> list[Cmd]:
        return [Cmd.STOP_SEARCHING]


@dataclass(frozen=True)
class FoundPartnerMsg(RealMsg):
    other_uid: Uid
    other_sex: Sex
    other_phone: str

    def format(self) -> str:
        if self.other_sex == Sex.MALE:
            return """
מצאתי [מתנגד|תומך] רפורמה שישמח לדבר עכשיו!

מספר הטלפון שלו הוא {}. גם העברתי לו את המספר שלך. מוזמ[ן/נת] להרים טלפון!
אחרי שתסיימו לדבר, מתי שתרצ[ה/י] עוד שיחה, לח[ץ/צי] על הכפתור.
""".format(
                self.other_phone
            )
        else:
            return """
מצאתי [מתנגדת|תומכת] רפורמה שתשמח לדבר עכשיו!

מספר הטלפון שלה הוא {}. גם העברתי לה את המספר שלך. מוזמ[ן/נת] להרים טלפון!
אחרי שתסיימו לדבר, מתי שתרצ[ה/י] עוד שיחה, לח[ץ/צי] על הכפתור.
""".format(
                self.other_phone
            )

    def cmds(self) -> list[Cmd]:
        return [Cmd.IM_AVAILABLE_NOW]


@dataclass(frozen=True)
class AreYouAvailableMsg(RealMsg):
    def format(self) -> str:
        return """
[מתנגד|תומכ]/ת רפורמה פנוי/ה לשיחה עכשיו. האם גם את[ה/] פנוי[/ה] לשיחה עכשיו?
"""

    def cmds(self) -> list[Cmd]:
        return [Cmd.IM_AVAILABLE_NOW]


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
