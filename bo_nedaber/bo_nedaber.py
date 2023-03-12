from __future__ import annotations

import logging
import re
import typing
from dataclasses import replace
from logging import debug
from pathlib import Path
from typing import (
    NoReturn,
    assert_never,
)

from fastapi import FastAPI, Request
from pydantic import BaseSettings

from .db import Db
from .models import (
    Sex,
    Opinion,
    UserStateBase,
    InitialState,
    Cmd,
    Msg,
    Sched,
    FoundPartnerMsg,
    AreYouAvailableMsg,
    RegisteredBase,
    Asking,
    Waiting,
    Active,
    WaitingForOpinion,
    WaitingForPhone,
    Inactive,
    UserState,
    Registered,
    Asked,
    GotPhoneMsg,
    RealMsg,
    SearchingMsg,
    UnexpectedReqMsg,
)
from .tg_models import (
    Message,
    TgMethod,
    ReplyKeyboardMarkup,
    KeyboardButton,
    SendMessageMethod,
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
SEARCH_DURATION = Duration(60)

MALE, FEMALE = Sex.MALE, Sex.FEMALE

PRO, CON = Opinion.PRO, Opinion.CON


def other_opinion(opinion: Opinion) -> Opinion:
    match opinion:
        case Opinion.PRO:
            return Opinion.CON
        case Opinion.CON:
            return Opinion.PRO
        case _:
            assert_never(opinion)


def handle_msg_initial_state(state: InitialState, db: Db) -> list[TgMethod]:
    db.set(WaitingForOpinion(uid=state.uid))
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
        SendMessageMethod(chat_id=state.uid, text=WELCOME_MSG, reply_markup=keyboard)
    ]


def get_unexpected(state: UserStateBase) -> list[TgMethod]:
    return [SendMessageMethod(chat_id=state.uid, text=UNEXPECTED_CMD_MSG)]


def handle_msg_waiting_for_opinion(
    state: WaitingForOpinion, db: Db, msg: Message
) -> list[TgMethod]:
    if not isinstance(msg.text, str):
        return get_unexpected(state)
    try:
        sex, opinion = REV_OPINION_BTNS[msg.text]
    except KeyError:
        return get_unexpected(state)
    db.set(WaitingForPhone(uid=state.uid, sex=sex, opinion=opinion))
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="שלח את מספר הטלפון שלי", request_contact=True)]
        ],
        is_persistent=True,
    )
    return [
        SendMessageMethod(
            chat_id=state.uid,
            text=adjust_str(ASK_PHONE_MSG, sex, opinion),
            reply_markup=keyboard,
        )
    ]


def get_send_message_method(msg: RealMsg) -> TgMethod:
    state = msg.state
    cmds = msg.cmds()
    text = adjust_str(msg.format(), state.sex, state.opinion)
    if not cmds:
        return SendMessageMethod(chat_id=state.uid, text=text)
    texts = [adjust_str(cmd_text[cmd], state.sex, state.opinion) for cmd in cmds]
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in texts]]
    )
    return SendMessageMethod(chat_id=state.uid, text=text, reply_markup=keyboard)


def handle_msg_waiting_for_phone(
    state: WaitingForPhone, db: Db, msg: Message
) -> list[TgMethod]:
    if (
        not msg.contact
        or msg.contact.user_id != state.uid
        or not msg.contact.phone_number
    ):
        return get_unexpected(state)
    db.set(
        Inactive(
            uid=state.uid,
            opinion=state.opinion,
            sex=state.sex,
            phone=msg.contact.phone_number,
        ),
    )
    return [get_send_message_method(GotPhoneMsg(state))]


def handle_req_registerd(
    state: Registered, db: Db, ts: Timestamp, req: Message
) -> list[TgMethod]:
    if not isinstance(req.text, str):
        return get_unexpected(state)
    try:
        cmd = text2cmd[req.text.strip()]
    except KeyError:
        return get_unexpected(state)
    msgs = handle_cmd(state, db, ts, cmd)
    methods = []
    for msg in msgs:
        if isinstance(msg, Sched):
            db.schedule(msg.state.uid, msg.ts)
        else:
            methods.append(get_send_message_method(msg))
    return methods


def handle_msg(state: UserState, db: Db, ts: Timestamp, msg: Message) -> list[TgMethod]:
    if isinstance(state, InitialState):
        return handle_msg_initial_state(state, db)
    elif isinstance(state, WaitingForOpinion):
        return handle_msg_waiting_for_opinion(state, db, msg)
    elif isinstance(state, WaitingForPhone):
        return handle_msg_waiting_for_phone(state, db, msg)
    elif isinstance(state, RegisteredBase):
        return handle_req_registerd(state, db, ts, msg)
    else:
        typing.assert_never(state)


def handle_cmd_inactive(state: Inactive, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if cmd == Cmd.IM_AVAILABLE_NOW:
        searching_until = ts + SEARCH_DURATION
        msgs: list[Msg] = [
            SearchingMsg(state),
            Sched(state, searching_until),
        ]
        msgs.extend(search_for_match(db, ts, state, searching_until))
        return msgs
    else:
        return [UnexpectedReqMsg(state)]


def handle_cmd(state: Registered, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if isinstance(state, Inactive):
        return handle_cmd_inactive(state, db, ts, cmd)
    elif isinstance(state, Asking):
        todo()
    elif isinstance(state, Waiting):
        todo()
    elif isinstance(state, Active):
        todo()
    elif isinstance(state, Asked):
        todo()
    else:
        typing.assert_never(state)


UNEXPECTED_CMD_MSG = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחת התגובות המוכנות מראש?"


def remove_word_wrap_newlines(s: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", " ", s).strip()


WELCOME_MSG = remove_word_wrap_newlines(
    """
שלום! אני בוט שמקשר בין אנשים שמתנגדים לרפורמה המשפטית ובין אנשים שתומכים בה.
אם אתם רוצים לשוחח בשיחת אחד-על-אחד עם מישהו שחושב אחרת מכם, אני אשמח לעזור!

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


cmd_text = {
    Cmd.IM_AVAILABLE_NOW: "אני פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך] רפורמה",
    Cmd.STOP_SEARCHING: "הפסק לחפש",
}

assert all(cmd in cmd_text for cmd in Cmd if cmd != Cmd.SCHED)

text2cmd = {
    adjust_str(text, sex, opinion): cmd
    for cmd, text in cmd_text.items()
    for sex in Sex
    for opinion in Opinion
}


def todo() -> NoReturn:
    assert False, "TODO"


def search_for_match(
    db: Db, ts: Timestamp, cur_state: RegisteredBase, searching_until: Timestamp
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
            FoundPartnerMsg(cur_state, state2.uid, state2.sex, state2.phone),
            FoundPartnerMsg(state2, cur_state.uid, cur_state.sex, cur_state.phone),
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
            return [AreYouAvailableMsg(state2), Sched(state2, asking_until)]
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