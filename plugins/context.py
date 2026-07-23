from pyrogram.enums import ChatType
from pyrogram.types import InlineQuery, Message

from plugins.helpers import get_thread_id
from services import (
    AnySettingsTarget,
    ChannelSettingsTarget,
    ForumTopicMemberSettingsTarget,
    ForumTopicSettingsTarget,
    GroupMemberSettingsTarget,
    GroupSettingsTarget,
    UserSettingsTarget,
)


def get_config_target(update: Message | InlineQuery, *, include_member: bool = True) -> AnySettingsTarget:
    """

    Args:
        update:
        include_member: 排除 member target

    Returns:

    """
    if isinstance(update, InlineQuery):
        return UserSettingsTarget(telegram_user_id=update.from_user.id)

    if update.chat and update.chat.id is not None and update.chat.type == ChatType.CHANNEL:
        return ChannelSettingsTarget(telegram_chat_id=update.chat.id)

    if not update.from_user:
        raise ValueError("缺少配置目标用户")

    thread_id = get_thread_id(update)

    if update.chat and update.chat.id is not None and thread_id:
        if include_member:
            return ForumTopicMemberSettingsTarget(
                telegram_chat_id=update.chat.id,
                telegram_thread_id=thread_id,
                telegram_user_id=update.from_user.id,
            )
        return ForumTopicSettingsTarget(telegram_chat_id=update.chat.id, telegram_thread_id=thread_id)

    if update.chat and update.chat.id is not None and update.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if include_member:
            return GroupMemberSettingsTarget(telegram_chat_id=update.chat.id, telegram_user_id=update.from_user.id)
        return GroupSettingsTarget(telegram_chat_id=update.chat.id)

    return UserSettingsTarget(telegram_user_id=update.from_user.id)
