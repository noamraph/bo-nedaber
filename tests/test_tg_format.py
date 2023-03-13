from __future__ import annotations

from bo_nedaber.tg_format import (
    PhoneEntity,
    TextEntity,
    TextMentionEntity,
    format_entities,
    get_entity_length,
    interlace_message,
)
from bo_nedaber.tg_models import MessageEntity, User


def test_get_entity_length() -> None:
    assert get_entity_length("abc") == 3
    assert get_entity_length("אבג") == 3
    assert get_entity_length("🙋") == 2
    assert get_entity_length("🙋א") == 3


def test_format_message() -> None:
    user = User(id=1234, is_bot=False, first_name="Yoyo")
    mention = TextMentionEntity("you", user)
    phone = PhoneEntity("+1234")
    s = "hello {}, your number is {}"
    entities = interlace_message(
        s,
        mention,
        phone,
    )
    assert entities == [
        TextEntity("hello "),
        mention,
        TextEntity(", your number is "),
        phone,
    ]

    s, ents = format_entities(entities)
    assert s == "hello you, your number is +1234"
    assert ents == [
        MessageEntity(type="text_mention", offset=6, length=3, user=user),
        MessageEntity(type="phone_number", offset=26, length=5),
    ]
