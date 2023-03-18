from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from .timestamp import Timestamp


class BaseModel(PydanticBaseModel):
    class Config:
        exclude_none = True
        # extra = Extra.forbid

        json_encoders = {
            Timestamp: lambda ts: ts.seconds,
        }


class User(BaseModel):
    id: int
    is_bot: bool | None
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None


class ChatType(Enum):
    private = "private"
    group = "group"
    supergroup = "supergroup"
    channel = "channel"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


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
    user: User | None


class Contact(BaseModel):
    phone_number: str
    first_name: str
    last_name: str | None
    user_id: int | None
    vcard: str | None


class Message(BaseModel):
    message_id: int
    from_: User | None = Field(alias="from")
    date: Timestamp
    chat: Chat
    text: str | None
    entities: list[MessageEntity] | None
    reply_to_message: Message | None
    contact: Contact | None


class CallbackQuery(BaseModel):
    id: str
    from_: User = Field(alias="from")
    message: Message | None
    chat_instance: str
    data: str | None


class Update(BaseModel):
    update_id: int
    message: Message | None
    callback_query: CallbackQuery | None


class KeyboardButton(BaseModel):
    text: str
    request_contact: bool | None


class ReplyKeyboardMarkup(BaseModel):
    keyboard: list[list[KeyboardButton]]
    is_persistent: bool | None
    one_time_keyboard: bool | None


class ReplyKeyboardRemove(BaseModel):
    remove_keyboard: bool


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: str | None


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: list[list[InlineKeyboardButton]]


class ParseMode(Enum):
    MARKDOWNV2 = "MarkdownV2"
    HTML = "HTML"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}.{self.name}"


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
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None

    @property
    def method_name(self) -> str:
        return "sendMessage"


class EditMessageText(TgMethod):
    chat_id: int
    message_id: int
    text: str
    parse_mode: ParseMode | None
    entities: list[MessageEntity] | None
    reply_markup: InlineKeyboardMarkup | None

    @property
    def method_name(self) -> str:
        return "editMessageText"


class AnswerCallbackQuery(TgMethod):
    callback_query_id: str
    text: str | None
    show_alert: bool = False

    @property
    def method_name(self) -> str:
        return "answerCallbackQuery"
