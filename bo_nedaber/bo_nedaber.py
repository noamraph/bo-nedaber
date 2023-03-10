from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum, auto
from logging import debug
from pathlib import Path
from typing import (
    Callable,
    Iterable,
    NewType,
    NoReturn,
    Protocol,
    Self,
    Tuple,
    TypeVar,
    assert_never,
)

from fastapi import FastAPI, Request
from pydantic import BaseSettings

from .tg_models import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    SendMessageMethod,
    TgMethod,
)
from .timestamp import Duration, Timestamp

app = FastAPI(on_startup=[lambda: logging.basicConfig(level=logging.DEBUG)])

basedir = Path(__file__).absolute().parent.parent


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str

    class Config:
        env_file = basedir / ".env"


config = Settings()


ASKING_DURATION = Duration(19)


class Sex(Enum):
    MALE = auto()
    FEMALE = auto()


MALE, FEMALE = Sex.MALE, Sex.FEMALE


class Opinion(Enum):
    PRO = auto()
    CON = auto()


PRO, CON = Opinion.PRO, Opinion.CON


def other_opinion(opinion: Opinion) -> Opinion:
    match opinion:
        case Opinion.PRO:
            return Opinion.CON
        case Opinion.CON:
            return Opinion.PRO
        case _:
            assert_never(opinion)


Uid = NewType("Uid", int)


def get_search_score(state: UserState, opinion: Opinion) -> Tuple[int, int] | None:
    """Return the priority for who should we connect to.
    Lower order means higher priority."""
    if not isinstance(state, Registered):
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


class Comparable(Protocol):
    @abstractmethod
    def __lt__(self, other: Self) -> bool:
        ...


T = TypeVar("T")
S = TypeVar("S", bound=Comparable)


def min_if(iterable: Iterable[T], *, key: Callable[[T], S | None]) -> T | None:
    best: T | None = None
    best_score: S | None = None
    for x in iterable:
        score = key(x)
        if score is not None:
            if best_score is None or score < best_score:
                best = x
                best_score = score
    return best


class Db:
    def __init__(self) -> None:
        self._user_state: dict[Uid, UserState] = {}

    def get(self, uid: Uid) -> UserState:
        try:
            return self._user_state[uid]
        except KeyError:
            return InitialState(uid=uid)

    def set(self, state: UserState) -> None:
        self._user_state[state.uid] = state

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        r = min_if(
            self._user_state.values(),
            key=lambda state: get_search_score(state, opinion),
        )
        assert isinstance(r, Waiting | Asking | Active | type(None))
        return r


UNEXPECTED_CMD_MSG = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחת התגובות המוכנות מראש?"


@dataclass(frozen=True)
class UserState(ABC):
    uid: Uid

    @abstractmethod
    def handle_msg(self, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
        ...

    @staticmethod
    def handle_ts(db: Db, ts: Timestamp) -> list[TgMethod]:
        """Handle a timestamp. By default, do nothing"""
        _ = db, ts
        return []

    def unexpected(self) -> list[TgMethod]:
        return [SendMessageMethod(chat_id=self.uid, text=UNEXPECTED_CMD_MSG)]


def remove_word_wrap_newlines(s: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", " ", s).strip()


WELCOME_MSG = remove_word_wrap_newlines(
    """
שלום! אני בוט שמקשר בין אנשים שמתנגדים לרפורמה המשפטית ובין אנשים שתומכים בה.
אם אתם רוצים לשוחח בשיחת אחד-על-אחד עם מישהו שחושב אחרת מכם, אני אשמח לעזור!

(לשון זכר/נקבה תשמש רק כדי שאדע איך לפנות אליך, ולא תועבר למשתמשים אחרים.)

מה העמדה שלך?
"""
)

OPINION_BTNS = {
    (FEMALE, CON): "אני מתנגדת לרפורמה" "\n🙅‍♀️",
    (FEMALE, PRO): "אני תומכת ברפורמה" "\n🙋‍♀️",
    (MALE, CON): "אני מתנגד לרפורמה" "\n🙅‍♂️",
    (MALE, PRO): "אני תומך ברפורמה" "\n🙋‍♂️",
}
REV_OPINION_BTNS = {v: k for k, v in OPINION_BTNS.items()}


@dataclass(frozen=True)
class InitialState(UserState):
    def handle_msg(self, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
        db.set(WaitingForOpinion(uid=self.uid))
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text=OPINION_BTNS[FEMALE, CON]),
                    KeyboardButton(text=OPINION_BTNS[FEMALE, PRO]),
                ],
                [
                    KeyboardButton(text=OPINION_BTNS[MALE, CON]),
                    KeyboardButton(text=OPINION_BTNS[MALE, PRO]),
                ],
            ],
            is_persistent=True,
        )
        return [
            SendMessageMethod(chat_id=self.uid, text=WELCOME_MSG, reply_markup=keyboard)
        ]


ASK_PHONE_MSG = """
מעולה. כדי לקשר אותך לאנשים ש[מתנגדים לרפורמה|תומכים ברפורמה], לח[ץ/צי] על הכפתור
למטה, שישתף איתי את מספר הטלפון שלך. אני לא אעביר את מספר הטלפון לאף אחד מלבד לאנשים
אחרים שירצו לדבר איתך.
"""

REPL_RE = re.compile(r"\[ ([^/|\]]*?) ([/|]) ([^/|\]]*?) ]", re.VERBOSE)


def adjust_str(s: str, sex: Sex, opinion: Opinion) -> str:
    s = remove_word_wrap_newlines(s)

    def repl(m: re.Match[str]) -> str:
        first, sep, second = m.groups()
        if sep == "/":
            if sex is Sex.MALE:
                return first
            elif sex is Sex.FEMALE:
                return second
            else:
                assert_never(sex)
        elif sep == "|":
            if opinion is Opinion.PRO:
                return first
            elif opinion is Opinion.CON:
                return second
            else:
                assert_never(opinion)
        else:
            assert False

    return REPL_RE.sub(repl, s)


class Cmd(Enum):
    IM_AVAILABLE_NOW = auto()
    STOP_SEARCHING = auto()


cmd_text = {
    Cmd.IM_AVAILABLE_NOW: "אני פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך] רפורמה",
    Cmd.STOP_SEARCHING: "הפסק לחפש",
}

text2cmd = {
    adjust_str(text, sex, opinion): cmd
    for cmd, text in cmd_text.items()
    for sex in Sex
    for opinion in Opinion
}


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


def todo() -> NoReturn:
    assert False, "TODO"


@dataclass(frozen=True)
class WaitingForOpinion(UserState):
    def handle_msg(self, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
        if not isinstance(msg.text, str):
            return self.unexpected()
        try:
            sex, opinion = REV_OPINION_BTNS[msg.text]
        except KeyError:
            return self.unexpected()
        db.set(WaitingForPhone(uid=self.uid, sex=sex, opinion=opinion))
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="שלח את מספר הטלפון שלי", request_contact=True)]
            ],
            is_persistent=True,
        )
        return [
            SendMessageMethod(
                chat_id=self.uid,
                text=adjust_str(ASK_PHONE_MSG, sex, opinion),
                reply_markup=keyboard,
            )
        ]


@dataclass(frozen=True)
class WithOpinion(UserState, ABC):
    sex: Sex
    opinion: Opinion

    def get_send_message_method(self, text: str, cmds: list[Cmd]) -> TgMethod:
        texts = [adjust_str(cmd_text[cmd], self.sex, self.opinion) for cmd in cmds]
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=text) for text in texts]]
        )
        return SendMessageMethod(
            chat_id=self.uid,
            text=adjust_str(text, self.sex, self.opinion),
            reply_markup=keyboard,
        )


GOT_PHONE_MSG = """
תודה, רשמתי את מספר הטלפון שלך. האם את[ה/] פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך] רפורמה?

כשתלח[ץ/צי] על הכפתור, אחפש [מתנגד|תומך] רפורמה שפנוי לשיחה עכשיו.
אם אמצא, אעביר לו את המספר שלך, ולך את המספר שלו.
"""


@dataclass(frozen=True)
class WaitingForPhone(WithOpinion):
    def handle_msg(self, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
        if (
            not msg.contact
            or msg.contact.user_id != self.uid
            or not msg.contact.phone_number
        ):
            return self.unexpected()
        db.set(
            Inactive(
                uid=self.uid,
                opinion=self.opinion,
                sex=self.sex,
                phone=msg.contact.phone_number,
            ),
        )
        return [self.get_send_message_method(GOT_PHONE_MSG, [Cmd.IM_AVAILABLE_NOW])]


@dataclass(frozen=True)
class Registered(WithOpinion, ABC):
    phone: str

    def handle_msg(self, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
        if not isinstance(msg.text, str):
            return self.unexpected()
        try:
            cmd = text2cmd[msg.text.strip()]
        except KeyError:
            return self.unexpected()
        return self.handle_cmd(db, ts, cmd)

    @abstractmethod
    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        ...

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


def search_for_match(
    db: Db, ts: Timestamp, cur_state: Registered, searching_until: Timestamp
) -> list[Msg]:
    state2 = db.search_for_user(other_opinion(cur_state.opinion))
    if isinstance(state2, Waiting):
        if state2.waiting_for is not None:
            state3 = db.get(state2.waiting_for)
            assert isinstance(state3, Asking)
            assert state3.waited_by == state2.waiting_for
            db.set(replace(state3, waited_by=None))
        db.set(cur_state.get_inactive())
        db.set(state2.get_inactive())
        return [
            FoundPartner(cur_state.uid, state2.uid),
            FoundPartner(state2.uid, cur_state.uid),
        ]
    elif isinstance(state2, Asking):
        assert state2.waited_by is None
        if state2.asking_until <= searching_until:
            db.set(cur_state.get_waiting(searching_until, state2.uid))
            db.set(replace(state2, waited_by=cur_state.uid))
            return []
        else:
            db.set(cur_state.get_waiting(searching_until, waiting_for=None))
            return []
    elif isinstance(state2, Active):
        asking_until = ts + ASKING_DURATION
        if asking_until <= searching_until:
            db.set(
                cur_state.get_asking(
                    searching_until, state2.uid, asking_until, waited_by=None
                )
            )
            db.set(state2.get_asked(ts, cur_state.uid))
            return [AreYouAvailable(state2.uid), Sched(state2.uid, asking_until)]
        else:
            db.set(cur_state.get_waiting(searching_until, waiting_for=None))
            return []
    elif state2 is None:
        db.set(cur_state.get_waiting(searching_until, waiting_for=None))
        return []
    else:
        assert_never(state2)


# def handle_im_available(db: Db, uid: Uid, ts: Timestamp) -> list[Msg]:
#     st0 = db.get(uid)
#     # It's quite obvious why handle_im_available() can be called for Inactive and Asked.
#     # It can also be called on Waiting: if the user is waiting for a Asking user,
#     # and the Asking user got accepted, we need another search for the Waiting user.
#     assert isinstance(st0, Inactive | Asked | Waiting)
#     msgs: list[Msg] = []
#     if isinstance(st0, Asked):
#         # If uid is being asked and replies "I'm available", there's a match.
#         uid2 = st0.asked_by
#         msgs.append(FoundPartner(uid, uid2))
#         db.set(st0.get_inactive())
#
#         st2 = db.get(uid2)
#         assert isinstance(st2, Asking)
#         msgs.append(FoundPartner(uid2, uid))
#         db.set(st2.get_inactive())
#         if st2.waited_by is not None:
#             # In order to be sure we're always consistent, we first change
#             # the state of the waiting user, so it won't be waiting for us, and
#             # then do another search for it. This extra write isn't really required,
#             # but I feel better with having it.
#             st3 = db.get(st2.waited_by)
#             assert isinstance(st3, Waiting)
#             assert st3.waiting_for == uid2
#             db.set(replace(st3, waiting_for=None))
#             msgs2 = handle_im_available(db, st2.waited_by, ts)
#             msgs.extend(msgs2)
#
#     elif isinstance(st0, Inactive | Waiting):
#         if isinstance(st0, Waiting):
#             assert st0.waiting_for is None
#         st2 = db.search_for_user(other_opinion(st0.opinion))
#         if st2 is not None:
#             uid2 = st2.uid
#             if isinstance(st2, Waiting):
#                 msgs.append(FoundPartner(uid, uid2))
#                 db.set(st0.get_inactive())
#                 msgs.append(FoundPartner(uid2, uid))
#                 db.set(st2.get_inactive())
#                 if st2.waiting_for is not None:
#                     st3 = db.get(st2.waiting_for)
#                     assert isinstance(st3, Asking)
#                     assert st3.waited_by == uid2
#                     db.set(replace(st3, waited_by=None))
#             elif isinstance(st2, Asking):
#                 assert st2.waited_by is None
#                 todo()
#
#         else:
#             todo()
#
#     else:
#         assert_never(st0)
#
#     return msgs


SEARCHING_MSG = """
מחפש...

({} שניות נותרו)
"""


@dataclass(frozen=True)
class Inactive(Registered):
    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        if cmd == Cmd.IM_AVAILABLE_NOW:
            return [
                self.get_send_message_method(
                    SEARCHING_MSG.format(60), [Cmd.STOP_SEARCHING]
                )
            ]
        else:
            return self.unexpected()


@dataclass(frozen=True)
class Searching(Registered, ABC):
    searching_until: Timestamp


@dataclass(frozen=True)
class Asking(Searching):
    asked_uid: Uid
    asking_until: Timestamp

    # If someone is waiting for us, their uid
    waited_by: Uid | None

    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@dataclass(frozen=True)
class Waiting(Searching):
    """
    The user is withing a minute of being available (ie. searching), but
    not asking anyone. He may be waiting for another user who is asking.
    """

    waiting_for: Uid | None

    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@dataclass(frozen=True)
class Active(Registered):
    since: Timestamp

    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@dataclass(frozen=True)
class Asked(Registered):
    since: Timestamp
    asked_by: Uid

    def handle_cmd(self, db: Db, ts: Timestamp, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}


@app.post("/tg/{token}", include_in_schema=False)
async def tg_webhook(token: str, request: Request) -> None:
    if token != config.tg_webhook_token:
        raise RuntimeError
    update = await request.json()
    debug(f"webhook: {update!r}")
