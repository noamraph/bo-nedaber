from __future__ import annotations

import logging
import re
import typing
from dataclasses import replace
from logging import debug
from pathlib import Path
from textwrap import dedent
from typing import NoReturn, assert_never

from fastapi import FastAPI, Request
from phonenumbers import PhoneNumberFormat, format_number
from phonenumbers import parse as phone_parse
from pydantic import BaseSettings

from .db import Db
from .models import (
    Active,
    AfterAskingTimedOut,
    AfterReplyUnavailableMsg,
    AfterStopSearchMsg,
    AreYouAvailableMsg,
    Asked,
    Asking,
    Cmd,
    FoundPartnerMsg,
    HowWasTheCallMsg,
    Inactive,
    InactiveMsg,
    InitialState,
    Msg,
    Opinion,
    RealMsg,
    Registered,
    RegisteredBase,
    RegisteredMsg,
    Searching,
    SearchingBase,
    SearchingMsg,
    SearchTimedOutMsg,
    Sex,
    ShouldRename,
    ThanksForAnsweringMsg,
    TypeNameMsg,
    Uid,
    UnexpectedReqMsg,
    UpdateSearchingMsg,
    UserState,
    UserStateBase,
    Waiting,
    WaitingForName,
    WaitingForOpinion,
    WaitingForPhone,
)
from .tg_format import (
    BotCommandEntity,
    PhoneEntity,
    TextMentionEntity,
    TgEntity,
    format_message,
)
from .tg_models import (
    EditMessageText,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    SendMessageMethod,
    TgMethod,
    Update,
    User,
)
from .timestamp import Duration, Timestamp

app = FastAPI(on_startup=[lambda: logging.basicConfig(level=logging.DEBUG)])

basedir = Path(__file__).absolute().parent.parent


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str
    postgres_url: str

    class Config:
        env_file = basedir / ".env"


config = Settings()


ASKING_DURATION = Duration(19)
SEARCH_DURATION = Duration(60)
SEARCH_UPDATE_INTERVAL = Duration(5)
assert SEARCH_DURATION.seconds % SEARCH_UPDATE_INTERVAL.seconds == 0
# Time until a survey appears
SURVEY_DURATION = Duration(60)

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


def handle_update_initial_state(uid: Uid, db: Db) -> list[TgMethod]:
    db.set(WaitingForOpinion(uid=uid))
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
    return [SendMessageMethod(chat_id=uid, text=WELCOME_MSG, reply_markup=keyboard)]


def get_unexpected(state: UserStateBase) -> list[TgMethod]:
    return [SendMessageMethod(chat_id=state.uid, text=UNEXPECTED_CMD_MSG)]


SEND_PHONE_BUTTON = """
👈 לח[ץ/צי] כאן כדי לשתף את מספר הטלפון שלך 👉

☎️
"""


def format_full_name(user: User) -> str:
    return f'{user.first_name} {user.last_name or ""}'.strip()


def handle_msg_waiting_for_opinion(
    state: WaitingForOpinion, db: Db, msg: Message
) -> list[TgMethod]:
    if not isinstance(msg.text, str):
        return get_unexpected(state)
    try:
        sex, opinion = REV_OPINION_BTNS[msg.text]
    except KeyError:
        return get_unexpected(state)
    assert msg.from_ is not None
    db.set(
        WaitingForPhone(
            uid=state.uid, name=format_full_name(msg.from_), sex=sex, opinion=opinion
        )
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=adjust_str(SEND_PHONE_BUTTON, sex, opinion),
                    request_contact=True,
                )
            ]
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


SEARCHING_TEXT = """\
מחפש...

({} שניות נותרו)
"""


def get_send_message_method(state: Registered, msg: RealMsg) -> TgMethod:
    entities: list[TgEntity] = []
    cmdss: list[list[Cmd]]
    if isinstance(msg, UnexpectedReqMsg):
        txt = "אני מצטער, לא הבנתי. תוכל[/י] ללחוץ על אחד הכפתורים בהודעה האחרונה?"
        cmdss = []
    elif isinstance(msg, TypeNameMsg):
        txt = "אין בעיה. [כתוב/כתבי] לי איך תרצ[ה/י] שאציג אותך 👇"
        cmdss = []
    elif isinstance(msg, RegisteredMsg):
        txt = """
            תודה. תופיע[/י] כך: {}, [תומך/תומכת|מתנגד/מתנגדת], {}.

            (אם תרצ[ה/י] לשנות משהו, שלח[/י] לי שוב את הפקודה {} ונתחיל מחדש.)
            """
        entities = [
            TextMentionEntity(state.name, User(id=state.uid)),
            PhoneEntity(state.phone),
            BotCommandEntity("/start"),
        ]
        cmdss = []
    elif isinstance(msg, InactiveMsg):
        txt = """
            האם את[ה/] פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך]?

            כשתלח[ץ/צי] על הכפתור, אחפש [מתנגד|תומך] שפנוי כרגע לשיחה עם [תומך|מתנגד].
            אם אמצא, אעביר לו את המספר שלך, ולך את המספר שלו.
            """
        cmdss = [[Cmd.IM_AVAILABLE_NOW]]
    elif isinstance(msg, SearchingMsg):
        txt = SEARCHING_TEXT.format(SEARCH_DURATION.seconds)
        cmdss = [[Cmd.STOP_SEARCHING]]
    elif isinstance(msg, FoundPartnerMsg):
        if msg.other_sex == MALE:
            txt = """
                מצאתי [מתנגד|תומך] שישמח לדבר עכשיו!

                שמו {}. מספר הטלפון שלו הוא {}. גם העברתי לו את המספר שלך. מוזמ[ן/נת] להרים טלפון!
                """
        else:
            txt = """
                מצאתי [מתנגדת|תומכת] שתשמח לדבר עכשיו!

                שמה {}. מספר הטלפון שלה הוא {}. גם העברתי לה את המספר שלך. מוזמ[ן/נת] להרים טלפון!
                """
        entities = [
            TextMentionEntity(msg.other_name, User(id=msg.other_uid)),
            PhoneEntity(msg.other_phone),
        ]
        cmdss = [[]]
    elif isinstance(msg, AreYouAvailableMsg):
        if msg.other_sex == MALE:
            txt = """
                [מתנגד|תומך] פנוי לשיחה עכשיו. האם גם את[ה/] פנוי[/ה] לשיחה עכשיו?
                """
        else:
            txt = """
                [מתנגדת|תומכת] פנויה לשיחה עכשיו. האם גם את[ה/] פנוי[/ה] לשיחה עכשיו?
                """
        cmdss = [[Cmd.ANSWER_AVAILABLE, Cmd.ANSWER_UNAVAILABLE]]
    elif isinstance(msg, AfterAskingTimedOut):
        txt = """
            אני מצטער, לא הספקת לענות בזמן.

            אבל אם תלח[ץ/צי] על הכפתור למטה אשמח לחפש [מתנגד|תומך] אחר!
            """
        cmdss = [[Cmd.IM_AVAILABLE_NOW]]
    elif isinstance(msg, AfterReplyUnavailableMsg):
        txt = """
            בסדר גמור. מוזמ[ן/נת] ללחוץ על הכפתור למטה כשיהיה לך מתאים לדבר!
            """
        cmdss = [[Cmd.IM_AVAILABLE_NOW]]
    elif isinstance(msg, SearchTimedOutMsg):
        txt = """
            לא מצאתי [מתנגד|תומך] פנוי בינתיים. אבל כש[מתנגד|תומך] יחפש מישהו לדבר איתו,
            אשלח לך שאלה האם את[ה/] פנוי[/ה].

            את[ה/] מוזמ[ן/נת] ללחוץ שוב על הכפתור למטה מתי שתרצ[ה/י], זה יקפיץ
            אותך לראש התור.
            """
        cmdss = [[Cmd.IM_AVAILABLE_NOW, Cmd.IM_NO_LONGER_AVAILABLE]]
    elif isinstance(msg, AfterStopSearchMsg):
        txt = """
            עצרתי את החיפוש. כשתרצ[ה/י], את[ה/] מוזמ[ן/נת] ללחוץ שוב על הכפתור למטה.
            """
        cmdss = [[Cmd.IM_AVAILABLE_NOW]]
    elif isinstance(msg, HowWasTheCallMsg):
        # We add a newline and a no-break space so the message will be wider
        # and the buttons will have more spacee
        txt = "אחרי שסיימתם - איך היתה השיחה?\n\u00A0"
        cmdss = [[Cmd.S1, Cmd.S2, Cmd.S3, Cmd.S4, Cmd.S5], [Cmd.S_NO_ANSWER]]
    elif isinstance(msg, ThanksForAnsweringMsg):
        if msg.reply in (Cmd.S1, Cmd.S2):
            txt = "😔 מצטער לשמוע! אולי השיחה הבאה תהיה טובה יותר? מוזמ[ן/נת] ללחוץ שוב על הכפתור ולנסות שוב 💪"
        elif msg.reply == Cmd.S3:
            txt = "תודה על המשוב! מוזמ[ן/נת] לנסות שוב כשיהיה לך נוח."
        elif msg.reply in (Cmd.S4, Cmd.S5):
            txt = "איזה יופי! מוזמ[ן/נת] ללחוץ שוב על הכפתור כשתרצ[ה/י]!"
        elif msg.reply == Cmd.S_NO_ANSWER:
            txt = "בסדר גמור. מוזמ[ן/נת] ללחוץ שוב על הכפתור לשיחה נוספת כשתרצ[ה/י]!"
        else:
            assert False
        cmdss = [[Cmd.IM_AVAILABLE_NOW]]
    else:
        assert_never(msg)
        assert False  # Just to make pycharm understand
    txt2 = dedent(txt).strip()
    txt3 = remove_word_wrap_newlines(txt2)
    txt4 = adjust_str(txt3, state.sex, state.opinion)
    text, ents = format_message(txt4, *entities)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=adjust_str(cmd_text[cmd], state.sex, state.opinion),
                    callback_data=cmd.value,
                )
                for cmd in cmds
            ]
            for cmds in cmdss
        ]
    )
    method = SendMessageMethod(
        chat_id=state.uid, text=text, entities=ents, reply_markup=keyboard
    )
    return method


def handle_msg_waiting_for_phone(
    state: WaitingForPhone, db: Db, msg: Message
) -> list[TgMethod]:
    if (
        not msg.contact
        or msg.contact.user_id != state.uid
        or not msg.contact.phone_number
    ):
        return get_unexpected(state)
    phone_number = phone_parse("+" + msg.contact.phone_number)
    phone = format_number(phone_number, PhoneNumberFormat.INTERNATIONAL).replace(
        " ", "-"
    )
    db.set(ShouldRename(state.uid, state.name, state.sex, state.opinion, phone))
    assert msg.from_ is not None
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=state.name, callback_data=Cmd.USE_DEFAULT_NAME.value
            ),
            InlineKeyboardButton(
                text=cmd_text[Cmd.USE_CUSTOM_NAME],
                callback_data=Cmd.USE_CUSTOM_NAME.value,
            ),
        ]
    ]
    return [
        # Currently there's no way to remove the reply keyboard and have an
        # inline keyboard in the same message. So we just send another message.
        # See https://stackoverflow.com/a/74758668/343036
        SendMessageMethod(
            chat_id=state.uid,
            text="קיבלתי.",
            reply_markup=ReplyKeyboardRemove(remove_keyboard=True),
        ),
        SendMessageMethod(
            chat_id=state.uid,
            text=adjust_str("איך תרצ[ה/י] שאציג אותך?", state.sex, state.opinion),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard),
        ),
    ]


def handle_msg_waiting_for_name(
    state: WaitingForName, db: Db, msg: Message
) -> list[TgMethod]:
    if not msg.text:
        return get_unexpected(state)
    name = msg.text.strip()
    state2 = Inactive(
        state.uid, name, state.sex, state.opinion, state.phone, survey_ts=None
    )
    db.set(state2)
    return [
        get_send_message_method(state2, RegisteredMsg(state2.uid)),
        get_send_message_method(state2, InactiveMsg(state2.uid)),
    ]


def handle_msgs(db: Db, msgs: list[Msg]) -> list[TgMethod]:
    methods: list[TgMethod] = []
    for msg in msgs:
        if isinstance(msg, UpdateSearchingMsg):
            text = SEARCHING_TEXT.format(msg.seconds_left)
            message_id = db.get_message_id(msg.uid)
            if message_id is not None:
                methods.append(
                    EditMessageText(
                        chat_id=msg.uid,
                        message_id=message_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=cmd_text[Cmd.STOP_SEARCHING],
                                        callback_data=Cmd.STOP_SEARCHING.value,
                                    )
                                ]
                            ]
                        ),
                    )
                )
        else:
            state = db.get(msg.uid)
            assert isinstance(state, RegisteredBase)
            methods.append(get_send_message_method(state, msg))
    return methods


def handle_update(
    state: UserState, db: Db, ts: Timestamp, update: Update
) -> list[TgMethod]:
    if isinstance(state, InitialState) or (
        update.message is not None and update.message.text == "/start"
    ):
        return handle_update_initial_state(state.uid, db)
    elif isinstance(state, (WaitingForOpinion, WaitingForPhone, WaitingForName)):
        if update.message is None:
            return get_unexpected(state)
        if isinstance(state, WaitingForOpinion):
            return handle_msg_waiting_for_opinion(state, db, update.message)
        elif isinstance(state, WaitingForPhone):
            return handle_msg_waiting_for_phone(state, db, update.message)
        elif isinstance(state, WaitingForName):
            return handle_msg_waiting_for_name(state, db, update.message)
        else:
            typing.assert_never(state)
    elif isinstance(state, RegisteredBase):
        if update.callback_query is None:
            return get_unexpected(state)
        try:
            cmd = Cmd(update.callback_query.data)
        except ValueError:
            return get_unexpected(state)
        msgs = handle_cmd(state, db, ts, cmd)
        methods = handle_msgs(db, msgs)
        return methods
    else:
        typing.assert_never(state)


def handle_cmd_should_rename(state: ShouldRename, db: Db, cmd: Cmd) -> list[Msg]:
    uid = state.uid
    state2: Registered
    if cmd == Cmd.USE_DEFAULT_NAME:
        state2 = state.get_inactive(survey_ts=None)
        db.set(state2)
        return [RegisteredMsg(uid), InactiveMsg(uid)]
    elif cmd == Cmd.USE_CUSTOM_NAME:
        state2 = WaitingForName(
            state.uid, state.name, state.sex, state.opinion, state.phone
        )
        db.set(state2)
        return [TypeNameMsg(uid)]
    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd_inactive(state: Inactive, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if cmd == Cmd.IM_AVAILABLE_NOW:
        is_found, msgs = search_for_match(db, ts, state)
        if not is_found:
            msgs.extend([SearchingMsg(state.uid)])
        return msgs
    elif cmd == Cmd.SCHED:
        db.set(state.get_inactive(survey_ts=None))
        return [HowWasTheCallMsg(state.uid)]
    elif cmd in (Cmd.S1, Cmd.S2, Cmd.S3, Cmd.S4, Cmd.S5, Cmd.S_NO_ANSWER):
        return [ThanksForAnsweringMsg(state.uid, cmd)]
    else:
        return [UnexpectedReqMsg(state.uid)]


def handle_cmd_active(state: Active, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if cmd == Cmd.IM_AVAILABLE_NOW:
        is_found, msgs = search_for_match(db, ts, state)
        if not is_found:
            msgs.extend([SearchingMsg(state.uid)])
        return msgs
    elif cmd == Cmd.IM_NO_LONGER_AVAILABLE:
        db.set(state.get_inactive(survey_ts=None))
        return [AfterReplyUnavailableMsg(state.uid)]
    else:
        return [UnexpectedReqMsg(state.uid)]


def round_up(n: int, m: int) -> int:
    return n + (-n % m)


def handle_cmd_searching(
    state: Searching, db: Db, ts: Timestamp, cmd: Cmd
) -> list[Msg]:
    uid = state.uid
    if cmd == Cmd.SCHED and state.searching_until > ts:
        # noinspection PyTypeChecker
        next_refresh = min(state.searching_until, ts + SEARCH_UPDATE_INTERVAL)
        db.set(replace(state, next_refresh=next_refresh))
        time_left = state.searching_until - ts
        assert time_left.seconds > 0
        return [
            UpdateSearchingMsg(
                uid, round_up(time_left.seconds, SEARCH_UPDATE_INTERVAL.seconds)
            ),
        ]
    elif cmd in (Cmd.SCHED, Cmd.STOP_SEARCHING):
        # Search timed out, or STOP_SEARCHING was pressed
        msgs: list[Msg]
        if cmd == Cmd.SCHED:
            db.set(state.get_active(since=ts))
            msgs = [SearchTimedOutMsg(uid)]
        elif cmd == Cmd.STOP_SEARCHING:
            db.set(state.get_inactive(survey_ts=None))
            msgs = [AfterStopSearchMsg(uid)]
        else:
            assert False

        if isinstance(state, Asking):
            asked = db.get(state.asked_uid)
            assert isinstance(asked, Asked)
            db.set(asked.get_inactive(survey_ts=None))
            msgs.append(AfterAskingTimedOut(state.asked_uid))
            if state.waited_by is not None:
                waiting = db.get(state.waited_by)
                assert isinstance(waiting, Waiting)
                _is_found, msgs2 = search_for_match(db, ts, waiting)
                msgs.extend(msgs2)
        elif isinstance(state, Waiting):
            if state.waiting_for is not None:
                asking = db.get(state.waiting_for)
                assert isinstance(asking, Asking)
                db.set(replace(asking, waited_by=None))
        else:
            assert_never(state)
        return msgs

    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd_asked(state: Asked, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    uid = state.uid
    other = db.get(state.asked_by)
    assert isinstance(other, Asking)
    msgs: list[Msg]
    if cmd == Cmd.ANSWER_AVAILABLE:
        msgs = [
            FoundPartnerMsg(uid, other.uid, other.name, other.sex, other.phone),
            FoundPartnerMsg(other.uid, uid, state.name, state.sex, state.phone),
        ]
        db.set(state.get_inactive(survey_ts=ts + SURVEY_DURATION))
        db.set(other.get_inactive(survey_ts=ts + SURVEY_DURATION))
        if other.waited_by is not None:
            waiting = db.get(other.waited_by)
            assert isinstance(waiting, Waiting)
            _is_found, msgs2 = search_for_match(db, ts, waiting)
            msgs.extend(msgs2)
        return msgs
    elif cmd in (Cmd.ANSWER_UNAVAILABLE, Cmd.SCHED):
        db.set(state.get_inactive(survey_ts=None))
        if cmd == Cmd.ANSWER_UNAVAILABLE:
            msgs = [AfterReplyUnavailableMsg(uid)]
        else:
            msgs = [AfterAskingTimedOut(uid)]
        _is_found, msgs2 = search_for_match(db, ts, other)
        msgs.extend(msgs2)
        return msgs
    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd(state: Registered, db: Db, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if isinstance(state, ShouldRename):
        return handle_cmd_should_rename(state, db, cmd)
    elif isinstance(state, WaitingForName):
        # Expecting a message, not a callback
        return [UnexpectedReqMsg(state.uid)]
    elif isinstance(state, Inactive):
        return handle_cmd_inactive(state, db, ts, cmd)
    elif isinstance(state, SearchingBase):
        return handle_cmd_searching(state, db, ts, cmd)
    elif isinstance(state, Asked):
        return handle_cmd_asked(state, db, ts, cmd)
    elif isinstance(state, Active):
        return handle_cmd_active(state, db, ts, cmd)
    else:
        typing.assert_never(state)


UNEXPECTED_CMD_MSG = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחת התגובות המוכנות מראש?"


def remove_word_wrap_newlines(s: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", " ", s).strip()


WELCOME_MSG = remove_word_wrap_newlines(
    """
שלום! אני בוט שמקשר בין אנשים שמתנגדים למהפכה המשטרית ובין אנשים שתומכים ברפורמה המשפטית.
אם אתם רוצים לשוחח בשיחת אחד-על-אחד עם מישהו שחושב אחרת מכם, אני אשמח לעזור!

מה העמדה שלך?
"""
)

OPINION_BTNS = {
    (FEMALE, CON): "אני מתנגדת למהפכה" "\n🙅‍♀️",
    (FEMALE, PRO): "אני תומכת ברפורמה" "\n🙋‍♀️",
    (MALE, CON): "אני מתנגד למהפכה" "\n🙅‍♂️",
    (MALE, PRO): "אני תומך ברפורמה" "\n🙋‍♂️",
}
REV_OPINION_BTNS = {v: k for k, v in OPINION_BTNS.items()}

ASK_PHONE_MSG = """
מעולה. כדי לקשר אותך לאנשים ש[מתנגדים|תומכים], לח[ץ/צי] על הכפתור
למטה, שישתף איתי את מספר הטלפון שלך. אני לא אעביר את מספר הטלפון לאף אחד מלבד לאנשים
אחרים שירצו לדבר איתך.
"""


def adjust_element(s: str, sex: Sex, opinion: Opinion) -> str:
    """
    A|B - according to opinion, PRO|CON
    A/B - according to sex, MALE/FEMALE
    A/B|C/D - according to both.
    """
    if "|" in s:
        parts = s.split("|")
        if len(parts) != 2:
            raise ValueError
        if "/" in parts[0]:
            partss = [part.split("/") for part in parts]
            if not all(len(parts) == 2 for parts in partss):
                raise ValueError
            return partss[opinion.value][sex.value]
        else:
            return parts[opinion.value]
    else:
        parts = s.split("/")
        if len(parts) != 2:
            raise ValueError
        return parts[sex.value]


def adjust_str(s: str, sex: Sex, opinion: Opinion) -> str:
    s = remove_word_wrap_newlines(s)

    def repl(m: re.Match[str]) -> str:
        return adjust_element(m.group(1), sex, opinion)

    return re.sub(r"\[(.+?)]", repl, s)


cmd_text = {
    Cmd.USE_CUSTOM_NAME: "שם אחר",
    Cmd.IM_AVAILABLE_NOW: "אני פנוי[/ה] עכשיו לשיחה עם [מתנגד|תומך]",
    Cmd.STOP_SEARCHING: "הפסק לחפש",
    Cmd.IM_NO_LONGER_AVAILABLE: "אני כבר לא פנוי[/ה]",
    Cmd.ANSWER_AVAILABLE: "✅ אני פנוי[/ה] עכשיו",
    Cmd.ANSWER_UNAVAILABLE: "❌ לא עכשיו",
    Cmd.S1: "☹",
    Cmd.S2: "🙁",
    Cmd.S3: "😐",
    Cmd.S4: "🙂",
    Cmd.S5: "☺",
    Cmd.S_NO_ANSWER: "מעדי[ף/פה] לא לענות",
}

assert all(
    cmd in cmd_text for cmd in Cmd if cmd not in (Cmd.SCHED, Cmd.USE_DEFAULT_NAME)
)


def todo() -> NoReturn:
    assert False, "TODO"


def search_for_match(
    db: Db, ts: Timestamp, state: Registered
) -> tuple[bool, list[Msg]]:
    """
    Return (is_found, msgs)
    """
    if isinstance(state, SearchingBase):
        searching_until = state.searching_until
        next_refresh = state.next_refresh
    else:
        searching_until = ts + SEARCH_DURATION
        next_refresh = ts + SEARCH_UPDATE_INTERVAL

    state2 = db.search_for_user(other_opinion(state.opinion))

    if isinstance(state2, Waiting):
        if state2.waiting_for is not None:
            state3 = db.get(state2.waiting_for)
            assert isinstance(state3, Asking)
            assert state3.waited_by == state2.waiting_for
            db.set(replace(state3, waited_by=None))
        db.set(state.get_inactive(survey_ts=ts + SURVEY_DURATION))
        db.set(state2.get_inactive(survey_ts=ts + SURVEY_DURATION))
        return True, [
            FoundPartnerMsg(
                state.uid, state2.uid, state2.name, state2.sex, state2.phone
            ),
            FoundPartnerMsg(state2.uid, state.uid, state.name, state.sex, state.phone),
        ]

    elif isinstance(state2, Asking):
        assert state2.waited_by is None
        if state2.asking_until <= searching_until:
            db.set(state.get_waiting(searching_until, next_refresh, state2.uid))
            db.set(replace(state2, waited_by=state.uid))
        else:
            db.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
        return False, []

    elif isinstance(state2, Active):
        asking_until = ts + ASKING_DURATION
        if asking_until <= searching_until:
            db.set(
                state.get_asking(
                    searching_until,
                    next_refresh,
                    state2.uid,
                    asking_until,
                    waited_by=None,
                )
            )
            db.set(state2.get_asked(asking_until, state.uid))
            return False, [
                AreYouAvailableMsg(state2.uid, state.sex),
            ]
        else:
            db.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
            return False, []
    elif state2 is None:
        db.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
        return False, []
    else:
        assert_never(state2)


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
