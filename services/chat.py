from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat
from repo.chat import ChatRepo


class ChatNotFoundError(Exception):
    pass


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.chat = ChatRepo(session)

    async def get(self, telegram_chat_id: int) -> Chat | None:
        return await self.chat.get_by_tg_chat_id(telegram_chat_id)

    async def get_or_raise(self, telegram_chat_id: int) -> Chat:
        if not (chat := await self.get(telegram_chat_id)):
            raise ChatNotFoundError(f"在数据库中找不到 Chat: {telegram_chat_id}")
        return chat
