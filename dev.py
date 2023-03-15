# pylint: skip-file

from __future__ import annotations

import sys
from typing import Any

import requests
import rich.pretty

from bo_nedaber.bo_nedaber import *
from bo_nedaber.db import *
from bo_nedaber.models import *

# noinspection PyUnresolvedReferences
from bo_nedaber.tg_format import *
from bo_nedaber.tg_models import *
from bo_nedaber.timestamp import *


def pprint(x: Any) -> None:
    rich.pretty.pprint(x, indent_guides=False)


def t_call(method: str, **kwargs: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    url = "https://api.telegram.org/bot{}/{}".format(config.telegram_token, method)
    r = requests.get(
        url,
        json={k: jsonable_encoder(v) for k, v in kwargs.items()},
        timeout=kwargs["timeout"] + 1 if "timeout" in kwargs else None,
    ).json()
    if not r["ok"]:
        raise RuntimeError(f"Request failed: {r['description']}")
    else:
        return r["result"]


req_offset = None


def get_updates(timeout: int = 10) -> list[Update]:
    # We need to call getUpdates with the last update_id+1, otherwise we'll get
    # the same updates again.
    global req_offset
    batch = t_call(
        "getUpdates",
        timeout=timeout,
        offset=req_offset,
        allowed_updates=["message", "callback_query"],
    )
    if batch:
        req_offset = batch[-1]["update_id"] + 1
    updates = [Update.parse_obj(x) for x in batch]
    return updates


def call_method(call: TgMethod) -> Any:
    return t_call(call.method_name, **call.dict(exclude_unset=True))


recv_updates: list[Update] = []
sent_calls: list[TgMethod] = []


def handle_calls(db: Db, calls: list[TgMethod]) -> None:
    for call in calls:
        pprint(repr(call))
        sent_calls.append(call)
        r = call_method(call)
        if isinstance(call, SendMessageMethod):
            msg = Message.parse_obj(r)
            db.set_message_id(Uid(call.chat_id), msg.message_id)


def handle_reqs(db: Db, timeout: int = 10) -> None:
    ts = Timestamp.now()
    for event in db.get_events(ts):
        state2 = db.get(event.uid)
        assert isinstance(state2, RegisteredBase)
        msgs = handle_cmd(state2, db, event.ts, Cmd.SCHED)
        calls = handle_msgs(db, msgs)
        handle_calls(db, calls)

    next_ts = db.get_next_ts()
    if next_ts is not None:
        timeout = max(1, min(timeout, (next_ts - Timestamp.now()).seconds))

    updates = get_updates(timeout)
    recv_updates.extend(updates)
    for update in updates:
        pprint(repr(update))
        if update.message is not None:
            state = db.get(Uid(update.message.chat.id))
        elif update.callback_query is not None:
            state = db.get(Uid(update.callback_query.from_.id))
        else:
            assert False, "unexpected update"

        calls = handle_update(state, db, ts, update)

        if update.callback_query is not None:
            calls.append(
                AnswerCallbackQuery(callback_query_id=update.callback_query.id)
            )

        handle_calls(db, calls)


def loop(db: Db) -> None:
    while True:
        print(".", end="")
        handle_reqs(db)


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
