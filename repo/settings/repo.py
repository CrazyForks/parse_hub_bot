from dataclasses import dataclass
from typing import Any, Self

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.settings import Settings, SettingsScope
from repo.settings.migrate import migrate
from repo.settings.schema import Config


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingsTarget:
    scope: SettingsScope
    user_id: int | None = None
    chat_id: int | None = None
    forum_topic_id: int | None = None

    @classmethod
    def user(cls, user_id: int) -> Self:
        return cls(scope=SettingsScope.USER, user_id=user_id)

    @classmethod
    def group(cls, chat_id: int) -> Self:
        return cls(scope=SettingsScope.GROUP, chat_id=chat_id)

    @classmethod
    def group_member(cls, chat_id: int, user_id: int) -> Self:
        return cls(scope=SettingsScope.GROUP_MEMBER, chat_id=chat_id, user_id=user_id)

    @classmethod
    def forum_topic(cls, forum_topic_id: int) -> Self:
        return cls(scope=SettingsScope.FORUM_TOPIC, forum_topic_id=forum_topic_id)

    @classmethod
    def forum_topic_member(cls, forum_topic_id: int, user_id: int) -> Self:
        return cls(scope=SettingsScope.FORUM_TOPIC_MEMBER, forum_topic_id=forum_topic_id, user_id=user_id)

    @classmethod
    def channel(cls, chat_id: int) -> Self:
        return cls(scope=SettingsScope.CHANNEL, chat_id=chat_id)

    def dump(self) -> dict[str, int | None | SettingsScope]:
        return {
            "scope": self.scope,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "forum_topic_id": self.forum_topic_id,
        }


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def config_from_raw(raw: dict[str, Any] | None) -> Config:
        config = Config.model_validate(raw) if raw else None
        return migrate(config)

    async def get(self, target: SettingsTarget) -> Settings | None:
        settings = await self._session.scalar(select(Settings).filter_by(**target.dump()))
        return settings

    async def add(self, target: SettingsTarget, config: Config | None = None) -> Settings:
        settings = Settings(
            **target.dump(),
            config=_config_dump(config or Config()),
        )
        self._session.add(settings)
        await self._session.flush()
        return settings

    async def get_config(self, target: SettingsTarget) -> Config:
        settings = await self.get(target)
        if not settings:
            return Config()
        original_raw = settings.config
        migrated_config = self.config_from_raw(original_raw)

        if _config_dump(migrated_config) != original_raw:
            await self._save_config(target, migrated_config)

        return migrated_config

    async def _save_config(self, target: SettingsTarget, config: Config) -> Settings:
        settings = await self.get(target)
        if not settings:
            return await self.add(target, config)
        settings.config = _config_dump(config)
        await self._session.flush()
        return settings

    async def patch_config(self, target: SettingsTarget, **kwargs: Any) -> Config:
        current = await self.get_config(target)
        config = Config.model_validate(current.model_dump() | kwargs)
        await self._save_config(target, config)
        return config


def _config_dump(config: Config) -> dict[str, Any]:
    return config.model_dump(mode="json")
