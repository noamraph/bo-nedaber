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


def get_reqs(timeout: int = 1) -> list[Message]:
    # We need to call getUpdates with the last update_id+1, otherwise we'll get
    # the same updates again.
    global req_offset
    batch = t_call(
        "getUpdates", timeout=timeout, offset=req_offset, allowed_updates=["message"]
    )
    if batch:
        req_offset = batch[-1]["update_id"] + 1
    reqs = [Update.parse_obj(x).message for x in batch]
    return reqs


def call_method(call: TgMethod) -> None:
    t_call(call.method_name, **call.dict(exclude_unset=True))


recv_reqs: list[Message] = []
sent_calls: list[TgMethod] = []


def handle_reqs(db: Db, timeout: int = 10) -> None:
    ts = Timestamp.now()
    for event in db.get_events(ts):
        state2 = db.get(event.uid)
        assert isinstance(state2, RegisteredBase)
        handle_cmd(state2, db, event.ts, Cmd.SCHED)
    messages = get_reqs(timeout)
    for msg in messages:
        pprint(repr(msg))
        recv_reqs.append(msg)
        uid = Uid(msg.chat.id)
        if msg.text == "/start":
            state: UserState = InitialState(uid=uid)
        else:
            state = db.get(uid)
        calls = handle_msg(state, db, msg.date, msg)
        for call in calls:
            pprint(repr(call))
            sent_calls.append(call)
            call_method(call)


def loop(db: Db) -> None:
    while True:
        print(".", end="")
        next_ts = db.get_next_ts()
        if next_ts is not None:
            timeout = min(10, (next_ts - Timestamp.now()).seconds)
        else:
            timeout = 10
        handle_reqs(db, timeout=timeout)


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
