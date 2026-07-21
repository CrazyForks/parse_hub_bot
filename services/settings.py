from dataclasses import dataclass
from typing import Any, Literal, TypedDict, Unpack

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.settings import SettingsScope
from repo.settings import DefaultMode, SettingsConfig, SettingsRepo
from repo.settings.repo import SettingsTarget
from repo.settings.schema import DEFAULT_CONFIG, ConfigMetadata, MergeStrategy
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


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.user = UserService(session)
        self.chat = ChatService(session)
        self.forum_topic = ForumTopicService(session)
        self.settings = SettingsRepo(session)

    async def get_config(self, target: AnySettingsTarget) -> SettingsConfig:
        return await self.get_effective_config(target)

    async def get_effective_config(self, target: AnySettingsTarget) -> SettingsConfig:
        chain = await self._resolve_config_chain(target)

        scoped_patches = [
            (settings_target.scope, await self.settings.get_raw_config(settings_target)) for settings_target in chain
        ]

        merged_patch = _merge_config_patches(scoped_patches)
        return _hydrate_config(merged_patch)

    async def get_config_by_user(self, telegram_user_id: int) -> SettingsConfig:
        return await self.get_config(UserSettingsTarget(telegram_user_id=telegram_user_id))

    async def get_config_by_group(self, telegram_chat_id: int) -> SettingsConfig:
        return await self.get_config(GroupSettingsTarget(telegram_chat_id=telegram_chat_id))

    async def get_config_by_group_member(self, telegram_chat_id: int, telegram_user_id: int) -> SettingsConfig:
        return await self.get_config(
            GroupMemberSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_user_id=telegram_user_id)
        )

    async def get_config_by_forum_topic(self, telegram_chat_id: int, telegram_thread_id: int) -> SettingsConfig:
        return await self.get_config(
            ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id)
        )

    async def get_config_by_forum_topic_member(
        self, telegram_chat_id: int, telegram_thread_id: int, telegram_user_id: int
    ) -> SettingsConfig:
        return await self.get_config(
            ForumTopicMemberSettingsTarget(
                telegram_chat_id=telegram_chat_id,
                telegram_thread_id=telegram_thread_id,
                telegram_user_id=telegram_user_id,
            )
        )

    async def get_config_by_channel(self, telegram_chat_id: int) -> SettingsConfig:
        return await self.get_config(ChannelSettingsTarget(telegram_chat_id=telegram_chat_id))

    async def patch_config(self, target: AnySettingsTarget, **kwargs: Unpack[ConfigPatch]) -> SettingsConfig:
        return await self.settings.patch_config(await self._resolve(target), **kwargs)

    async def patch_config_by_user(self, telegram_user_id: int, **kwargs: Unpack[ConfigPatch]) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(UserSettingsTarget(telegram_user_id=telegram_user_id)), **kwargs
        )

    async def patch_config_by_group(self, telegram_chat_id: int, **kwargs: Unpack[ConfigPatch]) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(GroupSettingsTarget(telegram_chat_id=telegram_chat_id)), **kwargs
        )

    async def patch_config_by_group_member(
        self, telegram_chat_id: int, telegram_user_id: int, **kwargs: Unpack[ConfigPatch]
    ) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(
                GroupMemberSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_user_id=telegram_user_id)
            ),
            **kwargs,
        )

    async def patch_config_by_forum_topic(
        self, telegram_chat_id: int, telegram_thread_id: int, **kwargs: Unpack[ConfigPatch]
    ) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(
                ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id)
            ),
            **kwargs,
        )

    async def patch_config_by_forum_topic_member(
        self, telegram_chat_id: int, telegram_thread_id: int, telegram_user_id: int, **kwargs: Unpack[ConfigPatch]
    ) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(
                ForumTopicMemberSettingsTarget(
                    telegram_chat_id=telegram_chat_id,
                    telegram_thread_id=telegram_thread_id,
                    telegram_user_id=telegram_user_id,
                )
            ),
            **kwargs,
        )

    async def patch_config_by_channel(self, telegram_chat_id: int, **kwargs: Unpack[ConfigPatch]) -> SettingsConfig:
        return await self.settings.patch_config(
            await self._resolve(ChannelSettingsTarget(telegram_chat_id=telegram_chat_id)), **kwargs
        )

    async def _resolve(self, target: AnySettingsTarget) -> SettingsTarget:
        match target:
            case UserSettingsTarget(telegram_user_id=telegram_user_id):
                user = await self.user.ensure(telegram_user_id)
                return SettingsTarget.user(user_id=user.id)
            case GroupSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.ensure_group(telegram_chat_id)
                return SettingsTarget.group(chat_id=chat.id)
            case GroupMemberSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_user_id=telegram_user_id):
                chat = await self.chat.ensure_group(telegram_chat_id)
                user = await self.user.ensure(telegram_user_id)
                return SettingsTarget.group_member(chat_id=chat.id, user_id=user.id)
            case ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id):
                forum_topic = await self.forum_topic.ensure(telegram_chat_id, telegram_thread_id)
                return SettingsTarget.forum_topic(forum_topic_id=forum_topic.id)
            case ForumTopicMemberSettingsTarget(
                telegram_chat_id=telegram_chat_id,
                telegram_thread_id=telegram_thread_id,
                telegram_user_id=telegram_user_id,
            ):
                forum_topic = await self.forum_topic.ensure(telegram_chat_id, telegram_thread_id)
                user = await self.user.ensure(telegram_user_id)
                return SettingsTarget.forum_topic_member(forum_topic_id=forum_topic.id, user_id=user.id)
            case ChannelSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.ensure_channel(telegram_chat_id)
                return SettingsTarget.channel(chat_id=chat.id)

    async def _resolve_config_chain(self, target: AnySettingsTarget) -> list[SettingsTarget]:
        match target:
            case UserSettingsTarget(telegram_user_id=telegram_user_id):
                user = await self.user.ensure(telegram_user_id)
                return [SettingsTarget.user(user_id=user.id)]

            case GroupSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.ensure_group(telegram_chat_id)
                return [SettingsTarget.group(chat_id=chat.id)]

            case GroupMemberSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_user_id=telegram_user_id):
                chat = await self.chat.ensure_group(telegram_chat_id)
                user = await self.user.ensure(telegram_user_id)
                return [
                    SettingsTarget.group_member(chat_id=chat.id, user_id=user.id),
                    SettingsTarget.group(chat_id=chat.id),
                    SettingsTarget.user(user_id=user.id),
                ]

            case ForumTopicSettingsTarget(telegram_chat_id=telegram_chat_id, telegram_thread_id=telegram_thread_id):
                chat = await self.chat.ensure_group(telegram_chat_id)
                forum_topic = await self.forum_topic.ensure(telegram_chat_id, telegram_thread_id)
                return [
                    SettingsTarget.forum_topic(forum_topic_id=forum_topic.id),
                    SettingsTarget.group(chat_id=chat.id),
                ]

            case ForumTopicMemberSettingsTarget(
                telegram_chat_id=telegram_chat_id,
                telegram_thread_id=telegram_thread_id,
                telegram_user_id=telegram_user_id,
            ):
                chat = await self.chat.ensure_group(telegram_chat_id)
                forum_topic = await self.forum_topic.ensure(telegram_chat_id, telegram_thread_id)
                user = await self.user.ensure(telegram_user_id)
                return [
                    SettingsTarget.forum_topic_member(forum_topic_id=forum_topic.id, user_id=user.id),
                    SettingsTarget.forum_topic(forum_topic_id=forum_topic.id),
                    SettingsTarget.group_member(chat_id=chat.id, user_id=user.id),
                    SettingsTarget.group(chat_id=chat.id),
                    SettingsTarget.user(user_id=user.id),
                ]

            case ChannelSettingsTarget(telegram_chat_id=telegram_chat_id):
                chat = await self.chat.ensure_channel(telegram_chat_id)
                return [SettingsTarget.channel(chat_id=chat.id)]


def _get_config_metadata(field_name: str) -> ConfigMetadata:
    field = SettingsConfig.model_fields[field_name]
    for metadata in field.metadata:
        if isinstance(metadata, ConfigMetadata):
            return metadata
    raise RuntimeError(f"配置字段 {field_name} 缺少 ConfigMetadata")


def _merge_config_patches(scoped_patches: list[tuple[SettingsScope, dict[str, Any]]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for field_name in SettingsConfig.model_fields:
        metadata = _get_config_metadata(field_name)

        values = [
            value
            for scope, patch in scoped_patches
            if scope in metadata.scopes and field_name in patch
            for value in [patch[field_name]]
        ]

        if not values:
            continue

        match metadata.merge_strategy:
            case MergeStrategy.UNION:
                result = []
                for value in values:
                    for item in value:
                        if item not in result:
                            result.append(item)
                merged[field_name] = result

            case MergeStrategy.POLICY | MergeStrategy.PREFERENCE | MergeStrategy.STRICT:
                merged[field_name] = values[0]

    return merged


def _hydrate_config(config_patch: dict[str, Any]) -> SettingsConfig:
    return SettingsConfig.model_validate(DEFAULT_CONFIG.model_dump(mode="json") | config_patch)
