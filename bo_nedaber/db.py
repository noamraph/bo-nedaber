from __future__ import annotations

import json
import os
from dataclasses import dataclass
from logging import debug
from queue import Queue
from threading import Thread
from typing import Callable, Self, assert_never, get_args

from bo_nedaber.mem_db import DbBase, MemDb, Tx
from bo_nedaber.models import (
    Active,
    Asking,
    Opinion,
    Uid,
    UserState,
    UserStateTuple,
    Waiting,
)
from psycopg import Connection, Cursor, connect

# random.randrange(2**63)
ADVISORY_LOCK_ID = 6566891594548310082

# This DB works similar to redis. Everything is stored in-memory. Upon initialization,
# we first load all the data from postgres. There is a thread which saves
# transactions to postgres, to be loaded next time.


name_to_state_class = {cls.__name__: cls for cls in get_args(UserState)}


def dump_state(state: UserState) -> str:
    s = state.to_json()
    d = json.loads(s)
    d["type"] = state.__class__.__name__
    return json.dumps(d)


def load_state(d: dict[str, object]) -> UserState:
    cls = name_to_state_class[d.pop("type")]
    state = cls.from_dict(d)
    assert isinstance(state, UserStateTuple)
    return state


TxData = dict[Uid, UserState]


@dataclass(frozen=True)
class LogData:
    kind: str
    data: object


class StoreThread(Thread):
    def __init__(self, conn: Connection, queue: Queue[TxData | LogData | None]):
        super().__init__(daemon=True)
        self.conn = conn
        self.queue = queue
        self.was_exception = False

    @staticmethod
    def insert_state(cur: Cursor, state: UserState) -> None:
        s = dump_state(state)
        cur.execute(
            "INSERT INTO states (uid, state) values (%s, %s) "
            "ON CONFLICT (uid) DO UPDATE SET state = EXCLUDED.state;",
            (state.uid, s),
        )

    def run(self) -> None:
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    # Sentinel value meaning should end
                    break
                elif isinstance(item, dict):
                    with self.conn.transaction():
                        with self.conn.cursor() as cur:
                            for state in item.values():
                                self.insert_state(cur, state)
                    debug(f"StoreThread: stored transaction with {len(item)} updates.")
                elif isinstance(item, LogData):
                    with self.conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO logs (kind, data) values (%s, %s);",
                            (item.kind, json.dumps(item.data)),
                        )
                else:
                    assert_never(item)
        except BaseException:
            self.was_exception = True
            raise


class Db(DbBase):
    _store_thread: StoreThread

    def __init__(self, postgres_url: str) -> None:
        self._mem_db = MemDb()

        self._conn: Connection = connect(
            postgres_url, autocommit=True, application_name=f"bn {os.getpid()}"
        )
        self._queue: Queue[TxData | LogData | None] = Queue()
        self._tx: DbTx | None = None
        conn = self._conn
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (ADVISORY_LOCK_ID,))
                row = cur.fetchone()
                assert row is not None
                (is_success,) = row
            if not is_success:
                conn.close()
                raise RuntimeError("Couldn't get lock on postgres DB")
            with conn.cursor() as cur:
                cur.execute("SELECT (state) FROM states;")
                for (state_d,) in cur:
                    assert isinstance(state_d, dict)
                    state = load_state(state_d)
                    self._mem_db.set(state)
            self._store_thread = StoreThread(conn, self._queue)
            self._store_thread.start()
        except Exception:
            conn.close()
            raise

    def get(self, uid: Uid) -> UserState:
        return self._mem_db.get(uid)

    def search_for_user(self, opinion: Opinion) -> Waiting | Asking | Active | None:
        return self._mem_db.search_for_user(opinion)

    def get_first_sched(self) -> UserState | None:
        return self._mem_db.get_first_sched()

    def log(self, kind: str, **data: object) -> None:
        self._queue.put(LogData(kind, data))

    def close(self) -> None:
        if not self._conn.closed:
            self._queue.put(None)
            self._store_thread.join()
            self._conn.close()

    def transaction(self) -> DbTx:
        if self._tx is not None:
            raise RuntimeError("Transaction already in progress")

        def log2(kind: str, data: dict[str, object]) -> None:
            self.log(kind, **data)

        self._tx = DbTx(self._mem_db, log2, self._close_tx)
        return self._tx

    def _close_tx(self, txdata: TxData) -> None:
        assert self._tx is not None
        self._tx = None
        if self._store_thread.was_exception:
            raise RuntimeError("Storing thread had an exception")
        self._queue.put(txdata)


class DbTx(Tx):
    def __init__(
        self,
        mem_db: MemDb,
        log: Callable[[str, dict[str, object]], None],
        on_close: Callable[[TxData], None],
    ):
        self._mem_db = mem_db
        self._log = log
        self._on_close = on_close

        self._txdata: TxData = TxData({})
        self._closed = False

    def get(self, uid: Uid) -> UserState:
        return self._mem_db.get(uid)

    def set(self, state: UserState) -> None:
        self._mem_db.set(state)
        self._txdata[state.uid] = state

    def log(self, kind: str, **data: object) -> None:
        self._log(kind, data)

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

    def __exit__(self, *exc_info: object) -> None:
        self.close()
