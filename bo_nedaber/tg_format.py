from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import assert_never

from .tg_models import MessageEntity, User


@dataclass(frozen=True)
class TgEntityBase(ABC):
    text: str


@dataclass(frozen=True)
class TextEntity(TgEntityBase):
    pass


@dataclass(frozen=True)
class PhoneEntity(TgEntityBase):
    pass


@dataclass(frozen=True)
class TextMentionEntity(TgEntityBase):
    user: User


@dataclass(frozen=True)
class BotCommandEntity(TgEntityBase):
    pass


TgEntity = TextEntity | PhoneEntity | TextMentionEntity | BotCommandEntity


def get_entity_length(s: str) -> int:
    return sum((1 if ord(c) <= 0xFFFF else 2) for c in s)


def format_entities(entities: list[TgEntity]) -> tuple[str, list[MessageEntity]]:
    offset = 0
    r: list[MessageEntity] = []
    for e in entities:
        length = get_entity_length(e.text)
        if isinstance(e, TextEntity):
            pass
        elif isinstance(e, PhoneEntity):
            r.append(MessageEntity(type="phone_number", offset=offset, length=length))
        elif isinstance(e, TextMentionEntity):
            r.append(
                MessageEntity(
                    type="text_mention", offset=offset, length=length, user=e.user
                )
            )
        elif isinstance(e, BotCommandEntity):
            r.append(MessageEntity(type="bot_command", offset=offset, length=length))
        else:
            assert_never(e)
        offset += length
    s = "".join(e.text for e in entities)
    return s, r


def interlace_message(msg: str, *entities: TgEntity) -> list[TgEntity]:
    """
    format_message("A {} B {}", e1, e2) -> [TextEntity("A "), e1, TextEntity(" B "), e2]
    """
    parts = msg.split("{}")
    if len(parts) != len(entities) + 1:
        raise ValueError(f"Expected {len(entities)} placeholders")
    r: list[TgEntity] = []
    for part, e in zip(parts[:-1], entities):
        if part != "":
            r.append(TextEntity(part))
        r.append(e)
    if parts[-1] != "":
        r.append(TextEntity(parts[-1]))
    return r


def format_message(msg: str, *entities: TgEntity) -> tuple[str, list[MessageEntity]]:
    return format_entities(interlace_message(msg, *entities))
