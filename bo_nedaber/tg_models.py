from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field

from .timestamp import Timestamp


class User(BaseModel):
    id: int
    is_bot: bool | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


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
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class MessageEntity(BaseModel):
    type: str
    offset: int
    length: int
    user: User | None = None


class Contact(BaseModel):
    phone_number: str
    first_name: str
    last_name: str | None = None
    user_id: int | None = None
    vcard: str | None = None


class Message(BaseModel):
    message_id: int
    from_: User | None = Field(None, alias="from")
    date: Timestamp
    chat: Chat
    text: str | None = None
    entities: list[MessageEntity] | None = None
    reply_to_message: Message | None = None
    contact: Contact | None = None


class CallbackQuery(BaseModel):
    id: str
    from_: User = Field(alias="from")
    message: Message | None = None
    chat_instance: str
    data: str | None = None


class Update(BaseModel):
    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None


class KeyboardButton(BaseModel):
    text: str
    request_contact: bool | None = None


class ReplyKeyboardMarkup(BaseModel):
    keyboard: list[list[KeyboardButton]]
    is_persistent: bool | None = None
    one_time_keyboard: bool | None = None


class ReplyKeyboardRemove(BaseModel):
    remove_keyboard: bool


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: str | None = None


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
    parse_mode: ParseMode | None = None
    entities: list[MessageEntity] | None = None
    disable_web_page_preview: bool = False
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = (
        None
    )

    @property
    def method_name(self) -> str:
        return "sendMessage"


class EditMessageText(TgMethod):
    chat_id: int
    message_id: int
    text: str
    parse_mode: ParseMode | None = None
    entities: list[MessageEntity] | None = None
    reply_markup: InlineKeyboardMarkup | None = None

    @property
    def method_name(self) -> str:
        return "editMessageText"


class DeleteMessage(TgMethod):
    chat_id: int
    message_id: int

    @property
    def method_name(self) -> str:
        return "deleteMessage"


class AnswerCallbackQuery(TgMethod):
    callback_query_id: str
    text: str | None = None
    show_alert: bool = False

    @property
    def method_name(self) -> str:
        return "answerCallbackQuery"
