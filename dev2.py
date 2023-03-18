from bo_nedaber.bo_nedaber import handle_update, SendErrorMessageMethod
from bo_nedaber.mem_db import DbBase
from bo_nedaber.models import SchedUpdate, Uid
from bo_nedaber.tg_models import Update, TgMethod, SendMessageMethod, Message
from bo_nedaber.timestamp import Duration, Timestamp
from dev import requester, MODS, call_method

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


def call_method_and_update_msg_ids(method: TgMethod, msg_ids: dict[Uid, int]) -> None:
    if isinstance(method, SendMessageMethod) and not isinstance(
        method, SendErrorMessageMethod
    ):
        uid = Uid(method.chat_id)
        # We first unset the last message_id, so if there's a problem
        # after the message is sent, we won't keep the old message_id.
        msg_ids.pop(uid, None)
        r = call_method(method)
        msg = Message.parse_obj(r)
        msg_ids[uid] = msg.message_id
    else:
        call_method(method)


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
