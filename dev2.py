import asyncio

import aiohttp

from bo_nedaber.bo_nedaber import handle_update
from bo_nedaber.mem_db import DbBase
from bo_nedaber.models import SchedUpdate, Uid
from bo_nedaber.tg_models import Update, TgMethod
from bo_nedaber.timestamp import Duration, Timestamp
from bo_nedaber import main
from bo_nedaber.main import config
from dev import requester, MODS, t_call

for mod in MODS:
    exec(f"from {mod} import *")


def get_update(
    db: DbBase, timeout: Duration = Duration(10)
) -> Update | SchedUpdate | None:
    ts = Timestamp.now()
    state = db.get_first_sched()
    wait_timeout = timeout
    update_if_didnt_get: SchedUpdate | None = None
    if state is not None:
        assert state.sched is not None
        if state.sched <= ts:
            return SchedUpdate(state.uid)
        if state.sched - ts <= timeout:
            wait_timeout = state.sched - ts
            update_if_didnt_get = SchedUpdate(state.uid)

    update = requester.get_update(wait_timeout)
    if update is not None:
        return update
    else:
        return update_if_didnt_get


async def async_call_method_and_update_msg_ids(
    method: TgMethod, msg_ids: dict[Uid, int]
) -> None:
    async with aiohttp.ClientSession() as client_session:
        return await main.call_method_and_update_msg_ids(
            client_session, msg_ids, method
        )


def call_method_and_update_msg_ids(method: TgMethod, msg_ids: dict[Uid, int]) -> None:
    asyncio.run(async_call_method_and_update_msg_ids(method, msg_ids))


def loop(db: DbBase, msg_ids: dict[Uid, int]) -> None:
    while True:
        update = get_update(db)
        if update is not None:
            print(update)
            with db.transaction() as tx:
                methods = handle_update(tx, msg_ids, Timestamp.now(), update)
            for method in methods:
                print(method)
                call_method_and_update_msg_ids(method, msg_ids)


def set_webhook() -> None:
    t_call(
        "setWebhook",
        url=f"https://bo-nedaber.herokuapp.com/tg/{config.tg_webhook_token}",
    )


def delete_webhook() -> None:
    t_call("deleteWebhook")
