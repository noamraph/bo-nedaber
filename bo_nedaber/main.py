from __future__ import annotations

import logging
from logging import debug
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseSettings
from starlette.requests import Request

from bo_nedaber.db import Db

basedir = Path(__file__).absolute().parent.parent


class Settings(BaseSettings):
    telegram_token: str
    tg_webhook_token: str
    postgres_url: str

    class Config:
        env_file = basedir / ".env"


config = Settings()

db: Db


def on_startup() -> None:
    global db
    logging.basicConfig(level=logging.DEBUG)
    db = Db(config.postgres_url)


app = FastAPI(on_startup=[on_startup])


@app.post(f"/tg/{config.tg_webhook_token}", include_in_schema=False)
async def tg_webhook(request: Request) -> None:
    update = await request.json()
    debug(f"webhook: {update!r}")
