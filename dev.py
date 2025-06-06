# pylint: skip-file

from __future__ import annotations

import asyncio
import logging
import sys
import time
from logging import debug
from queue import Empty, Queue
from threading import Thread

import aiohttp
import rich.pretty
from requests import ConnectTimeout

from bo_nedaber import main
from bo_nedaber.bo_nedaber import handle_update
from bo_nedaber.main import config
from bo_nedaber.mem_db import DbBase
from bo_nedaber.models import SchedUpdate, Uid
from bo_nedaber.tg_models import TgMethod, Update
from bo_nedaber.timestamp import Duration, Timestamp

# For convenience when developing.
# It's under "exec" so the linters won't get confused by this.
MODS = [
    "bo_nedaber.bo_nedaber",
    "bo_nedaber.db",
    "bo_nedaber.main",
    "bo_nedaber.mem_db",
    "bo_nedaber.models",
    "bo_nedaber.tg_models",
    "bo_nedaber.tg_format",
    "bo_nedaber.timestamp",
    "dev",
]

for mod in MODS:
    exec(f"from {mod} import *")


def pprint(x: object) -> None:
    rich.pretty.pprint(x, indent_guides=False)


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
            return Update.model_validate(obj)

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
                return Update.model_validate(obj)

        finally:
            self.is_waiting = False

    def _run_on_thread(self) -> None:
        try:
            debug("Requester: thread started")
            n_errors = 0
            while self.is_waiting:
                debug("Requester: calling getUpdates")
                try:
                    batch = call_method_base(
                        "getUpdates",
                        timeout=self.req_timeout.seconds,
                        offset=self.req_offset,
                        allowed_updates=["message", "callback_query"],
                    )
                    assert isinstance(batch, list)
                except (ConnectionError, ConnectTimeout) as e:
                    n_errors += 1
                    if n_errors > 3:
                        raise
                    logging.warning(e)
                    time.sleep(10)
                    continue
                else:
                    n_errors = 0
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


def reimp() -> None:
    """For debugging"""
    cmd = "import imp\n" + "\n".join(
        f"import {name}; imp.reload({name}); from {name} import *" for name in MODS
    )
    exec(cmd, sys.modules["__main__"].__dict__)


def enable_debug() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    # Only leave the root logger enabled
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.level = logging.WARN


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


async def async_call_method_base(method_name: str, **kwargs: object) -> object:
    async with aiohttp.ClientSession() as client_session:
        return await main.call_method_base(client_session, method_name, **kwargs)


def call_method_base(method_name: str, **kwargs: object) -> object:
    return asyncio.run(async_call_method_base(method_name, **kwargs))


async def async_call_method(method: TgMethod) -> object:
    async with aiohttp.ClientSession() as client_session:
        return await main.call_method(client_session, method)


def call_method(method: TgMethod) -> object:
    return asyncio.run(async_call_method(method))


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
            print(f"📩 {update!r}")
            with db.transaction() as tx:
                methods = handle_update(tx, msg_ids, Timestamp.now(), update)
            for method in methods:
                print(f"➡️ {method!r}")
                call_method_and_update_msg_ids(method, msg_ids)


def set_webhook() -> object:
    return call_method_base(
        "setWebhook",
        url=f"https://bo-nedaber.fly.dev/tg/{config.tg_webhook_token}",
    )


def delete_webhook() -> object:
    return call_method_base("deleteWebhook")
