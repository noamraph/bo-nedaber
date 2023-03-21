from __future__ import annotations

import re
import typing
from dataclasses import replace
from textwrap import dedent
from typing import NoReturn, assert_never

from .mem_db import Tx
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
    RegisteredMsg,
    SchedUpdate,
    Searching,
    SearchingBase,
    SearchingMsg,
    SearchTimedOutMsg,
    Sex,
    ShouldRename,
    ShouldRenameMsg,
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
    WhatIsYourOpinionMsg,
    WithOpinion,
    WithOpinionBase,
)
from .tg_format import BotCommandEntity, TextMentionEntity, TgEntity, format_message
from .tg_models import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageText,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    SendMessageMethod,
    TgMethod,
    Update,
    User,
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


def handle_update_initial_state(uid: Uid, tx: Tx, name: str) -> list[TgMethod]:
    state = WaitingForOpinion(uid=uid, name=name)
    tx.set(state)
    return get_send_message_methods(state, WhatIsYourOpinionMsg(uid), None)


class SendErrorMessageMethod(SendMessageMethod):
    """Work like SendMessageMethod, but don't keep the return message_id"""


def get_unexpected(state: UserStateBase) -> TgMethod:
    text0 = """
        אני מצטער, לא הבנתי. תוכלו ללחוץ על אחד הכפתורים בהודעה האחרונה?
        
        אם משהו לא ברור, אשמח אם תספרו לי ותשלחו לי צילום מסך לטלגרם, למשתמש {}. תודה!
        
        אפשר תמיד גם לשלוח את הפקודה {} כדי להתחיל מחדש.
    """
    text1 = dedent(text0).strip()
    text2 = remove_word_wrap_newlines(text1)
    text, ents = format_message(text2, TextMentionEntity('נעם', User(id=465241511)), BotCommandEntity('/start'))

    return SendErrorMessageMethod(chat_id=state.uid, text=text, entities=ents)


def format_full_name(user: User) -> str:
    return f'{user.first_name} {user.last_name or ""}'.strip()


SEARCHING_TEXT = """\
מחפש...

({} שניות נותרו)
"""


# pylint: disable=too-many-branches,too-many-statements,too-many-locals
def get_send_message_methods(
    state: UserState, msg: RealMsg, msg_ids: dict[Uid, int] | None
) -> list[TgMethod]:
    entities: list[TgEntity] = []
    cmdss: list[list[Cmd]] | None
    if isinstance(msg, UnexpectedReqMsg):
        return [get_unexpected(state)]
    elif isinstance(msg, WhatIsYourOpinionMsg):
        txt = """
            שלום! אני בוט שמקשר בין אנשים שמתנגדים למהפכה המשטרית ובין אנשים שתומכים ברפורמה המשפטית.
            אם אתם רוצים לשוחח בשיחת אחד-על-אחד עם מישהו שחושב אחרת מכם, אני אשמח לעזור!

            מה העמדה שלך?
            """
        cmdss = [[Cmd.FEMALE_CON, Cmd.FEMALE_PRO], [Cmd.MALE_CON, Cmd.MALE_PRO]]
    elif isinstance(msg, ShouldRenameMsg):
        txt = "מגניב. איך תרצ[ה/י] שאציג אותך?"
        cmdss = [[Cmd.USE_DEFAULT_NAME, Cmd.USE_CUSTOM_NAME]]
    elif isinstance(msg, TypeNameMsg):
        txt = "אין בעיה. [כתוב/כתבי] לי איך תרצ[ה/י] שאציג אותך 👇"
        cmdss = None
    elif isinstance(msg, RegisteredMsg):
        assert not isinstance(state, InitialState)
        txt = """
            תודה. תופיע[/י] כך: {}, [תומך/תומכת|מתנגד/מתנגדת].

            (אם תרצ[ה/י] לשנות משהו, שלח[/י] לי שוב את הפקודה {} ונתחיל מחדש.)
            """
        entities = [
            TextMentionEntity(state.name, User(id=state.uid)),
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

                שמו {}. גם העברתי לו את המשתמש שלך. מוזמ[ן/נת] להרים טלפון!
                """
        else:
            txt = """
                מצאתי [מתנגדת|תומכת] שתשמח לדבר עכשיו!

                שמה {}. גם העברתי לה את המשתמש שלך. מוזמ[ן/נת] להרים טלפון!
                """
        entities = [
            TextMentionEntity(msg.other_name, User(id=msg.other_uid)),
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
    if isinstance(state, WithOpinionBase):
        txt4 = adjust_str(txt3, state.sex, state.opinion)
    else:
        txt4 = txt3
    text, ents = format_message(txt4, *entities)
    replace_msg_id = msg_ids.get(msg.uid) if msg_ids is not None else None
    if isinstance(msg, AreYouAvailableMsg) and replace_msg_id is not None:
        delete_method = DeleteMessage(chat_id=state.uid, message_id=replace_msg_id)
        if msg_ids is not None:
            del msg_ids[msg.uid]
        replace_msg_id = None
    else:
        delete_method = None
    if replace_msg_id is not None:
        method: EditMessageText | SendMessageMethod = EditMessageText(
            chat_id=state.uid, message_id=replace_msg_id, text=text, entities=ents
        )
    else:
        method = SendMessageMethod(chat_id=state.uid, text=text, entities=ents)
    if cmdss is not None:
        method.reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=get_cmd_text(cmd, state),
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
    methods = typing.cast(
        list[TgMethod], [delete_method] if delete_method is not None else []
    ) + [method]
    return methods


def handle_update_waiting_for_name(
    state: WaitingForName, tx: Tx, msg: Message
) -> list[TgMethod]:
    if not msg.text:
        return [get_unexpected(state)]
    name = msg.text.strip()
    state2 = Inactive(state.uid, name, state.sex, state.opinion, survey_ts=None)
    tx.set(state2)
    return get_send_message_methods(
        state2, RegisteredMsg(state2.uid), None
    ) + get_send_message_methods(state2, InactiveMsg(state2.uid), None)


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
        assert isinstance(state, WithOpinionBase)
        return get_send_message_methods(state, msg, msg_ids)


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
        assert False  # for pylint


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
        if isinstance(update, SchedUpdate):
            # Ignore, if this happens
            return []
        assert update.message is not None
        assert update.message.from_ is not None
        name = format_full_name(update.message.from_)
        return handle_update_initial_state(uid, tx, name)
    elif isinstance(state, WaitingForName):
        # This is the only case where we don't expect an inline button press
        if isinstance(update, SchedUpdate):
            # Ignore, if this happens
            return []
        if update.message is None:
            return [get_unexpected(state)]
        return handle_update_waiting_for_name(state, tx, update.message)
    else:
        methods: list[TgMethod] = []
        if isinstance(update, SchedUpdate):
            cmd = Cmd.SCHED
        else:
            if update.callback_query is None:
                return [get_unexpected(state)]
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


def handle_cmd_waiting_for_opinion(
    state: WaitingForOpinion, tx: Tx, cmd: Cmd
) -> list[Msg]:
    if cmd == Cmd.MALE_PRO:
        sex, opinion = MALE, PRO
    elif cmd == Cmd.MALE_CON:
        sex, opinion = MALE, CON
    elif cmd == Cmd.FEMALE_PRO:
        sex, opinion = FEMALE, PRO
    elif cmd == Cmd.FEMALE_CON:
        sex, opinion = FEMALE, CON
    else:
        return [UnexpectedReqMsg(state.uid)]
    tx.set(ShouldRename(uid=state.uid, name=state.name, sex=sex, opinion=opinion))
    return [ShouldRenameMsg(state.uid)]


def handle_cmd_should_rename(state: ShouldRename, tx: Tx, cmd: Cmd) -> list[Msg]:
    uid = state.uid
    state2: WithOpinion
    if cmd == Cmd.USE_DEFAULT_NAME:
        state2 = state.get_inactive(survey_ts=None)
        tx.set(state2)
        return [RegisteredMsg(uid), InactiveMsg(uid)]
    elif cmd == Cmd.USE_CUSTOM_NAME:
        state2 = WaitingForName(state.uid, state.name, state.sex, state.opinion)
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
            FoundPartnerMsg(uid, other.uid, other.name, other.sex),
            FoundPartnerMsg(other.uid, uid, state.name, state.sex),
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


def handle_cmd(state: UserState, tx: Tx, ts: Timestamp, cmd: Cmd) -> list[Msg]:
    if isinstance(state, InitialState):
        return [UnexpectedReqMsg(state.uid)]
    elif isinstance(state, WaitingForOpinion):
        return handle_cmd_waiting_for_opinion(state, tx, cmd)
    elif isinstance(state, ShouldRename):
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
        assert False  # for pylint


def remove_word_wrap_newlines(s: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", " ", s).strip()


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
    Cmd.MALE_PRO: "אני תומך ברפורמה 🙋‍♂️",
    Cmd.MALE_CON: "אני מתנגד למהפכה 🙅‍♂️",
    Cmd.FEMALE_PRO: "אני תומכת ברפורמה 🙋‍♀️",
    Cmd.FEMALE_CON: "אני מתנגדת למהפכה 🙅‍♀️",
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


def get_cmd_text(cmd: Cmd, state: UserState) -> str:
    assert cmd != Cmd.SCHED
    if cmd == Cmd.USE_DEFAULT_NAME:
        assert isinstance(state, ShouldRename)
        return state.name
    if isinstance(state, WithOpinionBase):
        return adjust_str(cmd_text[cmd], state.sex, state.opinion)
    else:
        return cmd_text[cmd]


def todo() -> NoReturn:
    assert False, "TODO"


def search_for_match(
    tx: Tx, ts: Timestamp, state: WithOpinion
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
            FoundPartnerMsg(state.uid, state2.uid, state2.name, state2.sex),
            FoundPartnerMsg(state2.uid, state.uid, state.name, state.sex),
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
        assert False  # for pylint
