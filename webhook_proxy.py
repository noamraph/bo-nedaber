#!/usr/bin/env python3

# pylint: skip-file

from __future__ import annotations

import os
from typing import Any

import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_TOKEN = os.environ["TG_WEBHOOK_TOKEN"]


def t_call(method: str, **kwargs: Any) -> Any:
    url = "https://api.telegram.org/bot{}/{}".format(TELEGRAM_TOKEN, method)
    return requests.get(url, json=kwargs).json()


def main() -> None:
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Poll for updates, send to local webhook")
    parser.parse_args()

    offset = None
    while True:
        r = t_call("getUpdates", timeout=10, offset=offset)
        assert r["ok"] is True
        updates = r["result"]
        for update in updates:
            url = "http://localhost:8000/tg/{}".format(WEBHOOK_TOKEN)
            print(update)
            requests.post(url, json=update).raise_for_status()
            offset = update["update_id"] + 1


if __name__ == "__main__":
    main()
