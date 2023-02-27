from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel as PydanticBaseModel
from pydantic import Extra, Field

from .timestamp import Timestamp


class BaseModel(PydanticBaseModel):
    class Config:
        exclude_none = True
        extra = Extra.forbid
        # This is so the repr would be shorter and would reconstruct the value.
        # If there's a reason to change this, change this.
        use_enum_values = True

        json_encoders = {
            Timestamp: lambda ts: ts.seconds,
        }


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None


class ChatType(Enum):
    private = "private"
    group = "group"
    supergroup = "supergroup"
    channel = "channel"


class Chat(BaseModel):
    id: int
    type: ChatType
    username: str | None
    first_name: str | None
    last_name: str | None


class MessageEntity(BaseModel):
    type: str
    offset: int
    length: int


class Contact(BaseModel):
    phone_number: str
    first_name: str
    last_name: str | None
    user_id: int | None
    vcard: str | None


class Message(BaseModel):
    message_id: int
    from_: User | None = Field(None, alias="from")
    date: Timestamp
    chat: Chat
    text: str | None
    entities: list[MessageEntity] | None
    reply_to_message: Message | None
    contact: Contact | None


class Update(BaseModel):
    update_id: int
    message: Message


class KeyboardButton(BaseModel):
    text: str
    request_contact: bool | None


class ReplyKeyboardMarkup(BaseModel):
    keyboard: list[list[KeyboardButton]]
    is_persistent: bool | None


class ParseMode(Enum):
    MARKDOWNV2 = "MarkdownV2"
    HTML = "HTML"


class TgMethod(BaseModel, ABC):
    @property
    @abstractmethod
    def method_name(self) -> str:
        ...


class SendMessageMethod(TgMethod):
    chat_id: int
    text: str
    parse_mode: ParseMode | None
    entities: list[MessageEntity] | None
    disable_web_page_preview: bool = False
    reply_markup: ReplyKeyboardMarkup | None

    @property
    def method_name(self) -> str:
        return "sendMessage"
