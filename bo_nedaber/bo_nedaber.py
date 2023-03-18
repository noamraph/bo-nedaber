from __future__ import annotations

import re
import typing
from dataclasses import replace
from textwrap import dedent
from typing import NoReturn, assert_never

from phonenumbers import PhoneNumberFormat, format_number
from phonenumbers import parse as phone_parse

from .db import Tx
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
    UserStateBase,
    Waiting,
    WaitingForName,
    WaitingForOpinion,
    WaitingForPhone,
    SchedUpdate,
    WithOpinion,
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
    AnswerCallbackQuery,
)
from .timestamp import Duration, Timestamp

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


def handle_update_initial_state(uid: Uid, tx: Tx) -> list[TgMethod]:
    tx.set(WaitingForOpinion(uid=uid))
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


class SendErrorMessageMethod(SendMessageMethod):
    """Work like SendMessageMethod, but don't keep the return message_id"""


def get_unexpected(state: UserStateBase) -> TgMethod:
    if isinstance(state, WithOpinion):
        text = adjust_str(
            "אני מצטער, לא הבנתי. תוכל[/י] ללחוץ על אחד הכפתורים בהודעה האחרונה?",
            state.sex,
            state.opinion,
        )
    else:
        text = "אני מצטער, לא הבנתי. תוכלו ללחוץ על אחד הכפתורים בהודעה האחרונה?"
    return SendErrorMessageMethod(chat_id=state.uid, text=text)


SEND_PHONE_BUTTON = """
👈 לח[ץ/צי] כאן כדי לשתף את מספר הטלפון שלך 👉

☎️
"""


def format_full_name(user: User) -> str:
    return f'{user.first_name} {user.last_name or ""}'.strip()


def handle_update_waiting_for_opinion(
    state: WaitingForOpinion, tx: Tx, msg: Message
) -> list[TgMethod]:
    if not isinstance(msg.text, str):
        return [get_unexpected(state)]
    try:
        sex, opinion = REV_OPINION_BTNS[msg.text]
    except KeyError:
        return [get_unexpected(state)]
    assert msg.from_ is not None
    tx.set(
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


def get_send_message_method(
    state: Registered, msg: RealMsg, msg_ids: dict[Uid, int] | None
) -> TgMethod:
    entities: list[TgEntity] = []
    cmdss: list[list[Cmd]] | None
    if isinstance(msg, UnexpectedReqMsg):
        return get_unexpected(state)
    elif isinstance(msg, TypeNameMsg):
        txt = "אין בעיה. [כתוב/כתבי] לי איך תרצ[ה/י] שאציג אותך 👇"
        cmdss = None
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
        cmdss = None
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
        cmdss = None
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
        txt = "אחרי שסיימתם - עד כמה את[ה/] מרוצה מהשיחה?\n\u00A0"
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
    replace_msg_id = msg_ids.get(msg.uid) if msg_ids is not None else None
    if replace_msg_id is not None:
        method = EditMessageText(
            chat_id=state.uid, message_id=replace_msg_id, text=text, entities=ents
        )
    else:
        method = SendMessageMethod(chat_id=state.uid, text=text, entities=ents)
    if cmdss is not None:
        method.reply_markup = InlineKeyboardMarkup(
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
    else:
        if msg_ids is not None:
            msg_ids.pop(msg.uid, None)
    return method


def handle_update_waiting_for_phone(
    state: WaitingForPhone, tx: Tx, msg: Message
) -> list[TgMethod]:
    if (
        not msg.contact
        or msg.contact.user_id != state.uid
        or not msg.contact.phone_number
    ):
        return [get_unexpected(state)]
    phone_number = phone_parse("+" + msg.contact.phone_number)
    phone = format_number(phone_number, PhoneNumberFormat.INTERNATIONAL).replace(
        " ", "-"
    )
    tx.set(ShouldRename(state.uid, state.name, state.sex, state.opinion, phone))
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


def handle_update_waiting_for_name(
    state: WaitingForName, tx: Tx, msg: Message
) -> list[TgMethod]:
    if not msg.text:
        return [get_unexpected(state)]
    name = msg.text.strip()
    state2 = Inactive(
        state.uid, name, state.sex, state.opinion, state.phone, survey_ts=None
    )
    tx.set(state2)
    return [
        get_send_message_method(state2, RegisteredMsg(state2.uid), None),
        get_send_message_method(state2, InactiveMsg(state2.uid), None),
    ]


def handle_update_searching_msg(msg: UpdateSearchingMsg, message_id: int) -> TgMethod:
    text = SEARCHING_TEXT.format(msg.seconds_left)
    return EditMessageText(
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


def handle_msg(tx: Tx, msg_ids: dict[Uid, int], msg: Msg) -> list[TgMethod]:
    uid = msg.uid
    state = tx.get(uid)
    message_id = msg_ids.get(uid)
    if isinstance(msg, UpdateSearchingMsg):
        if message_id is not None:
            return [handle_update_searching_msg(msg, message_id)]
        else:
            return []
    else:
        assert isinstance(state, RegisteredBase)
        return [get_send_message_method(state, msg, msg_ids)]


def get_update_uid(update: Update | SchedUpdate) -> Uid:
    if isinstance(update, Update):
        if update.message is not None:
            return Uid(update.message.chat.id)
        elif update.callback_query is not None:
            return Uid(update.callback_query.from_.id)
        else:
            assert False, "unexpected update"
    elif isinstance(update, SchedUpdate):
        return update.uid
    else:
        assert_never(update)


def handle_update(
    tx: Tx, msg_ids: dict[Uid, int], ts: Timestamp, update: Update | SchedUpdate
) -> list[TgMethod]:
    uid = get_update_uid(update)
    state = tx.get(uid)
    if isinstance(state, InitialState) or (
        isinstance(update, Update)
        and update.message is not None
        and update.message.text == "/start"
    ):
        return handle_update_initial_state(uid, tx)
    elif isinstance(state, RegisteredBase) and not isinstance(state, WaitingForName):
        methods: list[TgMethod] = []
        if isinstance(update, SchedUpdate):
            cmd = Cmd.SCHED
        elif update.callback_query is None:
            return [get_unexpected(state)]
        else:
            methods.append(
                AnswerCallbackQuery(callback_query_id=update.callback_query.id)
            )
            try:
                cmd = Cmd(update.callback_query.data)
            except ValueError:
                return methods + [get_unexpected(state)]
        msgs = handle_cmd(state, tx, ts, cmd)
        for msg in msgs:
            methods.extend(handle_msg(tx, msg_ids, msg))
        return methods
    elif isinstance(state, (WaitingForOpinion, WaitingForPhone, WaitingForName)):
        if update.message is None:
            return [get_unexpected(state)]
        if isinstance(state, WaitingForOpinion):
            return handle_update_waiting_for_opinion(state, tx, update.message)
        elif isinstance(state, WaitingForPhone):
            return handle_update_waiting_for_phone(state, tx, update.message)
        elif isinstance(state, WaitingForName):
            return handle_update_waiting_for_name(state, tx, update.message)
        else:
            typing.assert_never(state)
    else:
        typing.assert_never(state)


def handle_cmd_should_rename(state: ShouldRename, tx: Tx, cmd: Cmd) -> list[Msg]:
    uid = state.uid
    state2: Registered
    if cmd == Cmd.USE_DEFAULT_NAME:
        state2 = state.get_inactive(survey_ts=None)
        tx.set(state2)
        return [RegisteredMsg(uid), InactiveMsg(uid)]
    elif cmd == Cmd.USE_CUSTOM_NAME:
        state2 = WaitingForName(
            state.uid, state.name, state.sex, state.opinion, state.phone
        )
        tx.set(state2)
        return [TypeNameMsg(uid)]
    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd_inactive(state: Inactive, tx: Tx, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if cmd == Cmd.IM_AVAILABLE_NOW:
        is_found, msgs = search_for_match(tx, ts, state)
        if not is_found:
            msgs.extend([SearchingMsg(state.uid)])
        return msgs
    elif cmd == Cmd.SCHED:
        tx.set(state.get_inactive(survey_ts=None))
        return [HowWasTheCallMsg(state.uid)]
    elif cmd in (Cmd.S1, Cmd.S2, Cmd.S3, Cmd.S4, Cmd.S5, Cmd.S_NO_ANSWER):
        return [ThanksForAnsweringMsg(state.uid, cmd)]
    else:
        return [UnexpectedReqMsg(state.uid)]


def handle_cmd_active(state: Active, tx: Tx, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if cmd == Cmd.IM_AVAILABLE_NOW:
        is_found, msgs = search_for_match(tx, ts, state)
        if not is_found:
            msgs.extend([SearchingMsg(state.uid)])
        return msgs
    elif cmd == Cmd.IM_NO_LONGER_AVAILABLE:
        tx.set(state.get_inactive(survey_ts=None))
        return [AfterReplyUnavailableMsg(state.uid)]
    else:
        return [UnexpectedReqMsg(state.uid)]


def round_up(n: int, m: int) -> int:
    return n + (-n % m)


def handle_cmd_searching(
    state: Searching, tx: Tx, ts: Timestamp, cmd: Cmd
) -> list[Msg]:
    uid = state.uid
    if cmd == Cmd.SCHED and state.searching_until > ts:
        # noinspection PyTypeChecker
        next_refresh = min(state.searching_until, ts + SEARCH_UPDATE_INTERVAL)
        tx.set(replace(state, next_refresh=next_refresh))
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
            tx.set(state.get_active(since=ts))
            msgs = [SearchTimedOutMsg(uid)]
        elif cmd == Cmd.STOP_SEARCHING:
            tx.set(state.get_inactive(survey_ts=None))
            msgs = [AfterStopSearchMsg(uid)]
        else:
            assert False

        if isinstance(state, Asking):
            asked = tx.get(state.asked_uid)
            assert isinstance(asked, Asked)
            tx.set(asked.get_inactive(survey_ts=None))
            msgs.append(AfterAskingTimedOut(state.asked_uid))
            if state.waited_by is not None:
                waiting = tx.get(state.waited_by)
                assert isinstance(waiting, Waiting)
                _is_found, msgs2 = search_for_match(tx, ts, waiting)
                msgs.extend(msgs2)
        elif isinstance(state, Waiting):
            if state.waiting_for is not None:
                asking = tx.get(state.waiting_for)
                assert isinstance(asking, Asking)
                tx.set(replace(asking, waited_by=None))
        else:
            assert_never(state)
        return msgs

    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd_asked(state: Asked, tx: Tx, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    uid = state.uid
    other = tx.get(state.asked_by)
    assert isinstance(other, Asking)
    msgs: list[Msg]
    if cmd == Cmd.ANSWER_AVAILABLE:
        msgs = [
            FoundPartnerMsg(uid, other.uid, other.name, other.sex, other.phone),
            FoundPartnerMsg(other.uid, uid, state.name, state.sex, state.phone),
        ]
        tx.set(state.get_inactive(survey_ts=ts + SURVEY_DURATION))
        tx.set(other.get_inactive(survey_ts=ts + SURVEY_DURATION))
        if other.waited_by is not None:
            waiting = tx.get(other.waited_by)
            assert isinstance(waiting, Waiting)
            _is_found, msgs2 = search_for_match(tx, ts, waiting)
            msgs.extend(msgs2)
        return msgs
    elif cmd in (Cmd.ANSWER_UNAVAILABLE, Cmd.SCHED):
        tx.set(state.get_inactive(survey_ts=None))
        if cmd == Cmd.ANSWER_UNAVAILABLE:
            msgs = [AfterReplyUnavailableMsg(uid)]
        else:
            msgs = [AfterAskingTimedOut(uid)]
        _is_found, msgs2 = search_for_match(tx, ts, other)
        msgs.extend(msgs2)
        return msgs
    else:
        return [UnexpectedReqMsg(uid)]


def handle_cmd(state: Registered, tx: Tx, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if isinstance(state, ShouldRename):
        return handle_cmd_should_rename(state, tx, cmd)
    elif isinstance(state, WaitingForName):
        # Expecting a message, not a callback
        return [UnexpectedReqMsg(state.uid)]
    elif isinstance(state, Inactive):
        return handle_cmd_inactive(state, tx, ts, cmd)
    elif isinstance(state, SearchingBase):
        return handle_cmd_searching(state, tx, ts, cmd)
    elif isinstance(state, Asked):
        return handle_cmd_asked(state, tx, ts, cmd)
    elif isinstance(state, Active):
        return handle_cmd_active(state, tx, ts, cmd)
    else:
        typing.assert_never(state)


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
    Cmd.IM_AVAILABLE_NOW: "✅ אני פנוי[/ה] עכשיו",
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
    tx: Tx, ts: Timestamp, state: Registered
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

    state2 = tx.search_for_user(other_opinion(state.opinion))

    if isinstance(state2, Waiting):
        if state2.waiting_for is not None:
            state3 = tx.get(state2.waiting_for)
            assert isinstance(state3, Asking)
            assert state3.waited_by == state2.waiting_for
            tx.set(replace(state3, waited_by=None))
        tx.set(state.get_inactive(survey_ts=ts + SURVEY_DURATION))
        tx.set(state2.get_inactive(survey_ts=ts + SURVEY_DURATION))
        return True, [
            FoundPartnerMsg(
                state.uid, state2.uid, state2.name, state2.sex, state2.phone
            ),
            FoundPartnerMsg(state2.uid, state.uid, state.name, state.sex, state.phone),
        ]

    elif isinstance(state2, Asking):
        assert state2.waited_by is None
        if state2.asking_until <= searching_until:
            tx.set(state.get_waiting(searching_until, next_refresh, state2.uid))
            tx.set(replace(state2, waited_by=state.uid))
        else:
            tx.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
        return False, []

    elif isinstance(state2, Active):
        asking_until = ts + ASKING_DURATION
        if asking_until <= searching_until:
            tx.set(
                state.get_asking(
                    searching_until,
                    next_refresh,
                    state2.uid,
                    asking_until,
                    waited_by=None,
                )
            )
            tx.set(state2.get_asked(asking_until, state.uid))
            return False, [
                AreYouAvailableMsg(state2.uid, state.sex),
            ]
        else:
            tx.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
            return False, []
    elif state2 is None:
        tx.set(state.get_waiting(searching_until, next_refresh, waiting_for=None))
        return False, []
    else:
        assert_never(state2)
