#!/usr/bin/env python3

# pylint: skip-file

from __future__ import annotations

import logging
import os
import time
from logging import info, warning
from typing import Any

import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
WEBHOOK_TOKEN = os.environ["TG_WEBHOOK_TOKEN"]

URL = f"http://localhost:8000/tg/{WEBHOOK_TOKEN}"


def t_call(method: str, **kwargs: Any) -> Any:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    return requests.get(url, json=kwargs).json()


def proxy() -> None:
    offset = None
    while True:
        try:
            r = t_call("getUpdates", timeout=60, offset=offset)
        except (requests.ConnectionError, requests.ConnectTimeout) as e:
            warning(e)
            time.sleep(10)
            continue

        assert r["ok"] is True
        updates = r["result"]
        for update in updates:
            info(update)
            requests.post(URL, json=update).raise_for_status()
            offset = update["update_id"] + 1


def main() -> None:
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Poll for updates, send to local webhook")
    parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    proxy()


if __name__ == "__main__":
    main()
