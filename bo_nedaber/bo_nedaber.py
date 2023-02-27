from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from enum import Enum, auto
from logging import debug
from typing import NewType, NoReturn, assert_never

from fastapi import FastAPI, Request
from pydantic import BaseModel, BaseSettings

from .tg_models import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    SendMessageMethod,
    TgMethod,
)
from .timestamp import Timestamp

app = FastAPI(on_startup=[lambda: logging.basicConfig(level=logging.DEBUG)])


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str

    class Config:
        env_file = ".env"


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


UNEXPECTED_CMD_MSG = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחת התגובות המוכנות מראש?"


class UserState(BaseModel, ABC):
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

    class Config:
        frozen = True


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


class WithOpinion(UserState, ABC):
    sex: Sex
    opinion: Opinion

    def get_send_message_method(self, text: str, cmds: list[Cmd]) -> TgMethod:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text=adjust_str(
                            cmd_text[cmd],
                            self.sex,
                            self.opinion,
                        )
                    )
                    for cmd in cmds
                ]
            ]
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


# class SearchingState(Registered):
#     # If we are asking, Who are we asking?
#     asked_uid: Uid | None
#     # If we are asking: if someone is waiting for us (if asked_uid will not approve), their uid.
#     # Should be None if asked_uid is None.
#     waiting_uid: Uid | None
#
#     def handle_msg(self, db: Db, msg: Message) -> list[TgMethod]:
#         todo()
#         return []


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
