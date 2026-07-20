from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.forum_topic import ForumTopic
from repo.chat import ChatRepo


class ForumTopicRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._chats = ChatRepo(session)

    async def get_by_chat_id_and_tg_thread_id(self, chat_id: int, telegram_thread_id: int) -> ForumTopic | None:
        topic = await self._session.scalar(
            select(ForumTopic).where(
                ForumTopic.chat_id == chat_id,
                ForumTopic.telegram_thread_id == telegram_thread_id,
            )
        )
        return topic
