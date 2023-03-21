from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from logging import debug
from pathlib import Path
from traceback import print_exc

from aiohttp import ClientSession
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from pydantic import BaseSettings
from starlette.requests import Request

from bo_nedaber.bo_nedaber import SendErrorMessageMethod, handle_update
from bo_nedaber.db import Db
from bo_nedaber.models import SchedUpdate, Uid
from bo_nedaber.tg_models import (
    EditMessageText,
    InlineKeyboardMarkup,
    Message,
    SendMessageMethod,
    TgMethod,
    Update,
)
from bo_nedaber.timestamp import Timestamp

basedir = Path(__file__).absolute().parent.parent


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str
    database_url: str

    class Config:
        env_file = basedir / ".env"


config = Settings()


@dataclass
class Globs:
    """Hold mutating globals"""

    db: Db
    msg_ids: dict[Uid, int]
    client_session: ClientSession


globs: Globs


async def on_startup() -> None:
    logging.basicConfig(level=logging.DEBUG)
    db = Db(config.database_url)
    msg_ids: dict[Uid, int] = {}
    client_session = ClientSession()
    global globs  # pylint: disable=global-statement
    globs = Globs(db, msg_ids, client_session)
    asyncio.create_task(scheduler())


async def on_shutdown() -> None:
    globs.db.close()
    await globs.client_session.close()


app = FastAPI(on_startup=[on_startup], on_shutdown=[on_shutdown])


async def call_method_base(client_session: ClientSession, method_name: str, **kwargs: object) -> object:
    url = f"https://api.telegram.org/bot{config.telegram_token}/{method_name}"
    async with client_session.get(url, json=kwargs) as resp:
        r = await resp.json()
        if not r["ok"]:
            if method_name == 'answerCallbackQuery':
                # answerCallbackQuery fails if not replied soon enough, and
                # it's OK, it's just used to stop the animation.
                return None
            else:
                raise RuntimeError(f"Request failed: {r['description']}")
        else:
            return r["result"]


async def call_method(client_session: ClientSession, method: TgMethod) -> object:
    d = method.dict(exclude_unset=True)
    d2 = {k: jsonable_encoder(v) for k, v in d.items()}
    return await call_method_base(client_session, method.method_name, **d2)


async def call_method_and_update_msg_ids(
    client_session: ClientSession, msg_ids: dict[Uid, int], method: TgMethod
) -> None:
    if isinstance(method, SendMessageMethod) and not isinstance(
        method, SendErrorMessageMethod
    ):
        # If there is an inline keyboard, store it. Otherwise, unset msg_ids[uid]
        uid = Uid(method.chat_id)
        # We first unset the last message_id, so if there's a problem
        # after the message is sent, we won't keep the old message_id.
        msg_ids.pop(uid, None)
        r = await call_method(client_session, method)
        if isinstance(method.reply_markup, InlineKeyboardMarkup):
            msg = Message.parse_obj(r)
            msg_ids[uid] = msg.message_id
    else:
        if isinstance(method, EditMessageText) and not isinstance(
            method.reply_markup, InlineKeyboardMarkup
        ):
            msg_ids.pop(Uid(method.chat_id), None)
        await call_method(client_session, method)


async def handle_update_and_call(update: Update | SchedUpdate) -> None:
    with globs.db.transaction() as tx:
        methods = handle_update(tx, globs.msg_ids, Timestamp.now(), update)
    for method in methods:
        debug(f"calling: {method!r}")
        await call_method_and_update_msg_ids(
            globs.client_session, globs.msg_ids, method
        )


@app.post(f"/tg/{config.tg_webhook_token}", include_in_schema=False)
async def tg_webhook(request: Request) -> None:
    update_d = await request.json()
    debug(f"webhook: {update_d!r}")
    update = Update.parse_obj(update_d)
    await handle_update_and_call(update)


async def scheduler() -> None:
    while True:
        ts = Timestamp.now()
        state = globs.db.get_first_sched()
        if state is not None and state.sched is not None and state.sched <= ts:
            # noinspection PyBroadException
            try:
                await handle_update_and_call(SchedUpdate(state.uid))
            except Exception:  # pylint: disable=broad-exception-caught
                print_exc()
        else:
            # Sleep until next second
            await asyncio.sleep(max(0.0, ts.seconds + 1.1 - time.time()))


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}
