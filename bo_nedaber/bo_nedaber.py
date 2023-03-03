from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from enum import Enum, auto
from logging import debug
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
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseSettings
from pydantic.dataclasses import dataclass as p_dataclass

from .tg_models import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    SendMessageMethod,
    TgMethod,
)
from .timestamp import Timestamp

app = FastAPI(on_startup=[lambda: logging.basicConfig(level=logging.DEBUG)])

basedir = Path(__file__).absolute().parent.parent


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str

    class Config:
        env_file = basedir / ".env"


config = Settings()


class Sex(Enum):
    MALE = auto()
    FEMALE = auto()


MALE, FEMALE = Sex.MALE, Sex.FEMALE


class Opinion(Enum):
    PRO = auto()
    CON = auto()


PRO, CON = Opinion.PRO, Opinion.CON

Uid = NewType("Uid", int)


def get_search_score(state: UserState, opinion: Opinion) -> Tuple[int, int] | None:
    """Return the priority for who should we connect to.
    Lower order means higher priority."""
    if not isinstance(state, Registered):
        return None
    if state.opinion != opinion:
        return None
    if isinstance(state, WaitingState):
        return 1, state.searching_since.seconds
    elif isinstance(state, AskingState) and state.waiting_uid is None:
        return 2, state.searching_since.seconds
    elif isinstance(state, Active):
        return 3, -state.active_since.seconds
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

    def get_user_state(self, uid: Uid) -> UserState:
        try:
            return self._user_state[uid]
        except KeyError:
            return InitialState(uid=uid)

    def set_user_state(self, state: UserState) -> None:
        self._user_state[state.uid] = state

    def search_for_user(self, opinion: Opinion) -> UserState | None:
        return min_if(
            self._user_state.values(),
            key=lambda state: get_search_score(state, opinion),
        )


UNEXPECTED_CMD_MSG = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחת התגובות המוכנות מראש?"


@p_dataclass(frozen=True)
class UserState(ABC):
    uid: Uid

    @abstractmethod
    def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
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


@p_dataclass(frozen=True)
class InitialState(UserState):
    def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
        db.set_user_state(WaitingForOpinion(uid=self.uid))
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


def todo() -> NoReturn:
    assert False, "TODO"


@p_dataclass(frozen=True)
class WaitingForOpinion(UserState):
    def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
        if not isinstance(msg.text, str):
            return self.unexpected()
        try:
            sex, opinion = REV_OPINION_BTNS[msg.text]
        except KeyError:
            return self.unexpected()
        db.set_user_state(WaitingForPhone(uid=self.uid, sex=sex, opinion=opinion))
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


@p_dataclass(frozen=True)
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


@p_dataclass(frozen=True)
class WaitingForPhone(WithOpinion):
    def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
        if (
            not msg.contact
            or msg.contact.user_id != self.uid
            or not msg.contact.phone_number
        ):
            return self.unexpected()
        db.set_user_state(
            Inactive(
                uid=self.uid,
                opinion=self.opinion,
                sex=self.sex,
                phone=msg.contact.phone_number,
            ),
        )
        return [self.get_send_message_method(GOT_PHONE_MSG, [Cmd.IM_AVAILABLE_NOW])]


@p_dataclass(frozen=True)
class Registered(WithOpinion, ABC):
    phone: str

    def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
        if not isinstance(msg.text, str):
            return self.unexpected()
        try:
            cmd = text2cmd[msg.text.strip()]
        except KeyError:
            return self.unexpected()
        return self.handle_cmd(db, cmd)

    @abstractmethod
    def handle_cmd(self, db: Db, cmd: Cmd) -> list[TgMethod]:
        ...


SEARCHING_MSG = """
מחפש...

({} שניות נותרו)
"""


@p_dataclass(frozen=True)
class Inactive(Registered):
    def handle_cmd(self, db: Db, cmd: Cmd) -> list[TgMethod]:
        if cmd == Cmd.IM_AVAILABLE_NOW:
            return [
                self.get_send_message_method(
                    SEARCHING_MSG.format(60), [Cmd.STOP_SEARCHING]
                )
            ]
        else:
            return self.unexpected()


@p_dataclass(frozen=True)
class SearchingState(Registered, ABC):
    searching_since: Timestamp


@p_dataclass(frozen=True)
class AskingState(SearchingState):
    asked_uid: Uid

    # If someone is waiting for us, their uid
    waiting_uid: Uid | None

    def handle_cmd(self, db: Db, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@p_dataclass(frozen=True)
class WaitingState(SearchingState):
    pass

    def handle_cmd(self, db: Db, cmd: Cmd) -> list[TgMethod]:
        todo()
        return []


@p_dataclass(frozen=True)
class Active(Registered):
    active_since: Timestamp

    def handle_cmd(self, db: Db, cmd: Cmd) -> list[TgMethod]:
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
