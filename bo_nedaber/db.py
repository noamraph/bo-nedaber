from __future__ import annotations

import json
import os
from logging import debug
from queue import Queue
from threading import Thread
from typing import Any, Callable, Self, get_args

from psycopg import Connection, Cursor, connect

from bo_nedaber.mem_db import DbBase, MemDb, Tx
from bo_nedaber.models import Active, Asking, Opinion, Uid, UserState, Waiting

# This DB works similar to redis. Everything is stored in-memory. Upon initialization,
# we first load all the data from postgres. There is a thread which saves
# transactions to postgres, to be loaded next time.


name_to_state_class = {cls.__name__: cls for cls in get_args(UserState)}


def dump_state(state: UserState) -> str:
    s = state.to_json()
    d = json.loads(s)
    d["type"] = state.__class__.__name__
    return json.dumps(d)


def load_state(s: str) -> UserState:
    d = json.loads(s)
    cls = name_to_state_class[d.pop("type")]
    return cls.from_dict(d)


TxData = dict[Uid, UserState]


class StoreThread(Thread):
    def __init__(self, conn: Connection, queue: Queue[TxData | None]):
        super().__init__(daemon=True)
        self.conn = conn
        self.queue = queue
        self.was_exception = False

    @staticmethod
    def insert_state(cur: Cursor, state: UserState):
        s = dump_state(state)
        cur.execute(
            "INSERT INTO states (uid, state) values (%s, %s) "
            "ON CONFLICT (uid) DO UPDATE SET state = EXCLUDED.state;",
            (state.uid, s),
        )

    def run(self) -> None:
        try:
            while True:
                txdata = self.queue.get()
                if txdata is None:
                    # Sentinel value meaning should end
                    break
                with self.conn.transaction():
                    with self.conn.cursor() as cur:
                        for state in txdata.values():
                            self.insert_state(cur, state)
                debug(f"StoreThread: stored transaction with {len(txdata)} updates.")
        except BaseException:
            self.was_exception = True
            raise


class Db(DbBase):
    def __init__(self, postgres_url: str) -> None:
        self._mem_db = MemDb()

        self._conn = conn = connect(
            postgres_url, autocommit=True, application_name=f"bn {os.getpid()}"
        )
        self._queue: Queue[UserState | None] = Queue()
        self._tx = None
        try:
            if "DYNO" not in os.environ:
                # It seems that heroku-postgres doesn't support this, so whatever...
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(0);")
                    (is_success,) = cur.fetchone()
                if not is_success:
                    conn.close()
                    raise RuntimeError("Couldn't get lock on postgres DB")
            with conn.cursor() as cur:
                cur.execute("SELECT (uid, state) FROM states;")
                for ((uid, state_s),) in cur:
                    state = load_state(state_s)
                    self._mem_db.set(state)
            self._store_thread = StoreThread(conn, self._queue)
            self._store_thread.start()
        except Exception:
            conn.close()
            raise

    def get(self, uid) -> UserState:
        return self._mem_db.get(uid)

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        return self._mem_db.search_for_user(opinion)

    def get_first_sched(self) -> UserState | None:
        return self._mem_db.get_first_sched()

    def close(self) -> None:
        if not self._conn.closed:
            self._queue.put(None)
            self._store_thread.join()
            self._conn.close()

    def transaction(self) -> DbTx:
        if self._tx is not None:
            raise RuntimeError("Transaction already in progress")
        self._tx = DbTx(self._mem_db, self._close_tx)
        return self._tx

    def _close_tx(self, txdata: TxData) -> None:
        assert self._tx is not None
        self._tx = None
        if self._store_thread.was_exception:
            raise RuntimeError("Storing thread had an exception")
        self._queue.put(txdata)


class DbTx(Tx):
    def __init__(self, mem_db: MemDb, on_close: Callable[[TxData], None]):
        self._mem_db = mem_db
        self._on_close = on_close

        self._txdata: TxData = {}
        self._closed = False

    def get(self, uid: Uid) -> UserState:
        return self._mem_db.get(uid)

    def set(self, state: UserState) -> None:
        self._mem_db.set(state)
        self._txdata[state.uid] = state

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        return self._mem_db.search_for_user(opinion)

    def get_first_sched(self) -> UserState | None:
        return self._mem_db.get_first_sched()

    def close(self) -> None:
        if self._closed:
            raise RuntimeError("Already closed")
        self._closed = True
        self._on_close(self._txdata)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
