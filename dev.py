from __future__ import annotations

import sys
from typing import Any

import requests
import rich.pretty

from bo_nedaber.bo_nedaber import *
from bo_nedaber.tg_models import *

"""
שלום! אני בוט שמקשר בין אנשים שמתנגדים לרפורמה המשפטית ואנשים שתומכים בה. אם אתם רוצים לשוחח בשיחת אחד-על-אחד עם מישהו שחושב אחרת מכם, אני אשמח לעזור!

(לשון זכר/נקבה תשמש רק כדי שאדע איך לפנות אליך, ולא תועבר למשתמשים אחרים.)

מה אתה?



מעולה. כדי לקשר אותך לאנשים שתומכים ברפורמה/מתנגדים לרפורמה, לחצ/י על הכפתור למטה, שישתף איתי את מספר הטלפון שלך. אני לא אעביר את מספר הטלפון לאף אחד מלבד לאנשים אחרים שירצו לדבר איתך.

"""


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


def get_messages(timeout: int = 1) -> list[Message]:
    # We need to call getUpdates with the last update_id+1, otherwise we'll get
    # the same updates again.
    messages: list[Message] = []
    offset = None
    while True:
        batch = t_call(
            "getUpdates", timeout=timeout, offset=offset, allowed_updates=["message"]
        )
        messages.extend(Update.parse_obj(x).message for x in batch)
        if batch:
            offset = batch[-1]["update_id"] + 1
        else:
            return messages


def call_method(call: TgMethod) -> None:
    t_call(call.method_name, **call.dict(exclude_unset=True))


recv_msgs = []
sent_calls = []


def handle_messages(db: Db) -> None:
    messages = get_messages()
    for msg in messages:
        pprint(repr(msg))
        recv_msgs.append(msg)
        uid = Uid(msg.chat.id)
        if msg.text == "/start":
            state: UserState = InitialState(uid=uid)
        else:
            state = db.get_user_state(uid)
        calls = state.handle_msg(db, msg)
        for call in calls:
            pprint(repr(call))
            sent_calls.append(call)
            call_method(call)


def reimp() -> None:
    """For debugging"""
    cmd = (
        "import imp\n"
        "import bo_nedaber\n"
        "imp.reload(bo_nedaber)\n"
        "from bo_nedaber import *\n"
        "import tg_models\n"
        "imp.reload(tg_models)\n"
        "from tg_models import *\n"
        "import dev\n"
        "imp.reload(dev)\n"
        "from dev import *\n"
    )
    exec(cmd, sys.modules["__main__"].__dict__)
