# pylint: skip-file

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from logging import debug
from queue import Empty, Queue
from threading import Thread
from typing import Any

import requests
import rich.pretty

from bo_nedaber.bo_nedaber import (
    adjust_str,
    cmd_text,
    config,
    handle_cmd,
    handle_msg,
    handle_update,
)
from bo_nedaber.mem_db import DbBase, MemDb
from bo_nedaber.models import Cmd, RegisteredBase, SearchingBase, Uid, UserState
from bo_nedaber.tg_models import (
    AnswerCallbackQuery,
    EditMessageText,
    Message,
    SendMessageMethod,
    TgMethod,
    Update,
)
from bo_nedaber.timestamp import Duration, Timestamp

# For convenience when developing.
# It's under "exec" so the linters won't get confused by this.
exec(
    """
from bo_nedaber.mem_db import *
from bo_nedaber.bo_nedaber import *
from bo_nedaber.db import *
from bo_nedaber.models import *
from bo_nedaber.tg_format import *
from bo_nedaber.tg_models import *
from bo_nedaber.timestamp import *
"""
)


def pprint(x: Any) -> None:
    rich.pretty.pprint(x, indent_guides=False)


def t_call(method: str, **kwargs: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    url = "https://api.telegram.org/bot{}/{}".format(config.telegram_token, method)
    r = requests.get(
        url,
        json={k: jsonable_encoder(v) for k, v in kwargs.items()},
        timeout=kwargs["timeout"] + 10 if "timeout" in kwargs else 60,
    ).json()
    if not r["ok"]:
        raise RuntimeError(f"Request failed: {r['description']}")
    else:
        return r["result"]


req_offset = None


class Requester:
    def __init__(self, req_timeout: Duration = Duration(10)):
        self.req_timeout = req_timeout
        self.req_offset = None
        self.queue: Queue[object] = Queue()
        self.thread: Thread | None = None
        self.is_waiting = False
        self.was_exception = False

    def get_update(self, timeout: Duration) -> Update | None:
        """Will block at most timeout"""
        if self.was_exception:
            self.was_exception = False
            raise RuntimeError("Thread for getting updates had an exception")

        # First, if there's something in the queue, return it.
        try:
            obj = self.queue.get(block=False)
        except Empty:
            pass
        else:
            return Update.parse_obj(obj)

        self.is_waiting = True
        try:
            # If the thread is not active, start it
            if self.thread is None or not self.thread.is_alive():
                self.thread = Thread(target=self._run_on_thread, daemon=True)
                self.thread.start()
            try:
                obj = self.queue.get(timeout=timeout.seconds)
            except Empty:
                return None
            else:
                return Update.parse_obj(obj)

        finally:
            self.is_waiting = False

    def _run_on_thread(self) -> None:
        try:
            debug("Requester: thread started")
            while self.is_waiting:
                debug("Requester: calling getUpdates")
                batch = t_call(
                    "getUpdates",
                    timeout=self.req_timeout.seconds,
                    offset=self.req_offset,
                    allowed_updates=["message", "callback_query"],
                )
                if batch:
                    self.req_offset = batch[-1]["update_id"] + 1
                    debug(f"Requester: got {len(batch)} updates")
                for x in batch:
                    self.queue.put(x)
            debug("Request thread ended")
        except Exception:
            self.was_exception = True
            raise


requester = Requester()
get_update = requester.get_update


def call_method(call: TgMethod) -> Any:
    return t_call(call.method_name, **call.dict(exclude_unset=True))


recv_updates: list[Update] = []
sent_calls: list[TgMethod] = []


def handle_calls(db: DbBase, calls: list[TgMethod]) -> None:
    for call in calls:
        pprint(repr(call))
        sent_calls.append(call)
        r = call_method(call)
        if isinstance(call, SendMessageMethod):
            uid = Uid(call.chat_id)
            state = db.get(uid)
            if isinstance(state, SearchingBase):
                msg = Message.parse_obj(r)
                with db.transaction() as tx:
                    tx.set(replace(state, message_id=msg.message_id))


def get_replied_text(state: UserState, cmd: Cmd) -> str:
    if not isinstance(state, RegisteredBase):
        # Unexpected, but whatever
        return ""
    if cmd in (Cmd.IM_AVAILABLE_NOW, Cmd.STOP_SEARCHING):
        # No need to append the button text
        return ""
    if cmd == Cmd.USE_DEFAULT_NAME:
        text = state.name
    else:
        text = adjust_str(cmd_text[cmd], state.sex, state.opinion)
    return "\n\n(ענית: {})".format(text)


def process_update(db: DbBase, ts: Timestamp, update: Update) -> None:
    pprint(update)
    if update.message is not None:
        state = db.get(Uid(update.message.chat.id))
    elif update.callback_query is not None:
        state = db.get(Uid(update.callback_query.from_.id))
    else:
        assert False, "unexpected update"

    calls: list[TgMethod] = []
    if update.callback_query is not None:
        # TODO: remove the button "stop searching" if a search was succeessful.
        cq = update.callback_query
        calls.append(AnswerCallbackQuery(callback_query_id=cq.id))
        if cq.message is not None and cq.message.text is not None:
            # Remove the buttons
            text = cq.message.text + get_replied_text(state, Cmd(cq.data))
            calls.append(
                EditMessageText(
                    chat_id=state.uid, message_id=cq.message.message_id, text=text
                )
            )

    with db.transaction() as tx:
        calls.extend(handle_update(state, tx, ts, update))

    handle_calls(db, calls)


def handle_req(db: DbBase, timeout: Duration = Duration(10)) -> bool:
    ts = Timestamp.now()
    state2 = db.get_first_sched()
    wait_timeout: Duration
    if state2 is not None:
        assert state2.sched is not None
        if state2.sched <= ts:
            assert isinstance(state2, RegisteredBase)
            with db.transaction() as tx:
                msgs = handle_cmd(state2, tx, ts, Cmd.SCHED)
            calls = [method for msg in msgs for method in handle_msg(tx, msg)]
            handle_calls(db, calls)
            return True
        else:
            # noinspection PyTypeChecker
            wait_timeout = min(timeout, state2.sched - ts)
    else:
        wait_timeout = timeout

    update = get_update(wait_timeout)
    if update is not None:
        recv_updates.append(update)
        process_update(db, Timestamp.now(), update)
        return True
    else:
        return False


def loop(db: MemDb) -> None:
    while True:
        got_req = handle_req(db)
        if not got_req:
            print(".", end="")


def reimp() -> None:
    """For debugging"""
    mods = [
        "bo_nedaber.bo_nedaber",
        "bo_nedaber.db",
        "bo_nedaber.models",
        "bo_nedaber.tg_models",
        "bo_nedaber.tg_format",
        "dev",
    ]
    cmd = "import imp\n" + "\n".join(
        f"import {name}; imp.reload({name}); from {name} import *" for name in mods
    )
    exec(cmd, sys.modules["__main__"].__dict__)


def enable_debug() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    # Only leave the root logger enabled
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.level = logging.WARN
