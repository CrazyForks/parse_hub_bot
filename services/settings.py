from dataclasses import dataclass
from typing import Literal, TypedDict, Unpack

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.settings import SettingsScope
from repo.settings import Config, DefaultMode, SettingsRepo
from repo.settings.repo import SettingsTarget
from services.chat import ChatService
from services.forum_topic import ForumTopicService
from services.user import UserService


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSettingsTarget:
    scope: Literal[SettingsScope.USER] = SettingsScope.USER
    telegram_user_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupSettingsTarget:
    scope: Literal[SettingsScope.GROUP] = SettingsScope.GROUP
    telegram_chat_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupMemberSettingsTarget:
    scope: Literal[SettingsScope.GROUP_MEMBER] = SettingsScope.GROUP_MEMBER
    telegram_user_id: int
    telegram_chat_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ForumTopicSettingsTarget:
    scope: Literal[SettingsScope.FORUM_TOPIC] = SettingsScope.FORUM_TOPIC
    telegram_chat_id: int
    telegram_thread_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ForumTopicMemberSettingsTarget:
    scope: Literal[SettingsScope.FORUM_TOPIC_MEMBER] = SettingsScope.FORUM_TOPIC_MEMBER
    telegram_user_id: int
    telegram_chat_id: int
    telegram_thread_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelSettingsTarget:
    scope: Literal[SettingsScope.CHANNEL] = SettingsScope.CHANNEL
    telegram_chat_id: int


type AnySettingsTarget = (
    UserSettingsTarget
    | GroupSettingsTarget
    | GroupMemberSettingsTarget
    | ForumTopicSettingsTarget
    | ForumTopicMemberSettingsTarget
    | ChannelSettingsTarget
)


class ConfigPatch(TypedDict, total=False):
    default_mode: DefaultMode
    auto_delete_url: bool
    disabled_platforms: list[str]
    enable_inline_raw_url: bool
    keep_error_log: bool
    hide_source: bool
    noprogress: bool


class TelegramSettingsTarget:
    @staticmethod
    def user(telegram_user_id: int) -> UserSettingsTarget:
        return UserSettingsTarget(telegram_user_id=telegram_user_id)

    @staticmethod
    def group(telegram_chat_id: int) -> GroupSettingsTarget:
        return GroupSettingsTarget(telegram_chat_id=telegram_chat_id)

    @staticmethod
    def group_member(telegram_user_id: int, telegram_chat_id: int) -> GroupMemberSettingsTarget:
        return GroupMemberSettingsTarget(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
        )

    @staticmethod
    def forum_topic(telegram_chat_id: int, telegram_thread_id: int) -> ForumTopicSettingsTarget:
        return ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id)

    @staticmethod
    def forum_topic_member(
        telegram_user_id: int, telegram_chat_id: int, telegram_thread_id: int
    ) -> ForumTopicMemberSettingsTarget:
        return ForumTopicMemberSettingsTarget(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_thread_id=telegram_thread_id,
        )

    @staticmethod
    def channel(telegram_chat_id: int) -> ChannelSettingsTarget:
        return ChannelSettingsTarget(telegram_chat_id=telegram_chat_id)


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.user = UserService(session)
        self.chat = ChatService(session)
        self.forum_topic = ForumTopicService(session)
        self.settings = SettingsRepo(session)

    async def get_config(self, target: AnySettingsTarget) -> Config:
        return await self.settings.get_config(await self._resolve(target))

    async def patch_config(self, target: AnySettingsTarget, **kwargs: Unpack[ConfigPatch]) -> Config:
        return await self.settings.patch_config(await self._resolve(target), **kwargs)

    async def _resolve(self, target: AnySettingsTarget) -> SettingsTarget:
        match target:
            case UserSettingsTarget(telegram_user_id=telegram_user_id):
                user = await self.user.get_or_raise(telegram_user_id)
                return SettingsTarget.user(user_id=user.id)
            case GroupSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.get_or_raise(telegram_chat_id)
                return SettingsTarget.group(chat_id=chat.id)
            case GroupMemberSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_user_id=telegram_user_id):
                chat = await self.chat.get_or_raise(telegram_chat_id)
                user = await self.user.get_or_raise(telegram_user_id)
                return SettingsTarget.group_member(chat_id=chat.id, user_id=user.id)
            case ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id):
                forum_topic = await self.forum_topic.get_or_raise(telegram_chat_id, telegram_thread_id)
                return SettingsTarget.forum_topic(forum_topic_id=forum_topic.id)
            case ForumTopicMemberSettingsTarget(
                telegram_chat_id=telegram_chat_id,
                telegram_thread_id=telegram_thread_id,
                telegram_user_id=telegram_user_id,
            ):
                forum_topic = await self.forum_topic.get_or_raise(telegram_chat_id, telegram_thread_id)
                user = await self.user.get_or_raise(telegram_user_id)
                return SettingsTarget.forum_topic_member(forum_topic_id=forum_topic.id, user_id=user.id)
            case ChannelSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.get_or_raise(telegram_chat_id)
                return SettingsTarget.channel(chat_id=chat.id)
