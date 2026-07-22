import asyncio
from typing import Any

from easy_ai18n import PreLocaleSelector
from pyrogram import Client
from pyrogram.errors import FloodWait, Forbidden, SlowmodeWait
from pyrogram.types import LinkPreviewOptions, Message

from core import bs
from log import logger
from plugins.helpers import format_label
from repo.settings import SettingsConfig
from services import StatusReporter

logger = logger.bind(name="ParseReporter")


class MessageStatusReporter(StatusReporter):
    """基于 Telegram Message 的状态报告器"""

    def __init__(self, user_msg: Message, *, _t: PreLocaleSelector, config: SettingsConfig):
        self._user_msg = user_msg
        self._msg: Message | None = None
        self._t = _t
        self._config = config

    async def report(self, text: str) -> None:
        if self._config.noprogress:
            return
        await self._edit_text(format_label(text))

    async def report_error(self, stage: str, error: Exception) -> None:
        t = format_label(self._t(f"{stage}错误:"))
        text = self._t(f"{t} \n```\n{error}```")
        if bs.demo_mode:
            text += self._t("\n\n**问题反馈: @MisakaSisters**")
        await self._edit_text(
            text,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        if self._config.keep_error_log:
            return

        async def fn() -> None:
            await asyncio.sleep(15)
            if self._msg:
                await self._msg.delete()

        loop = asyncio.get_running_loop()
        loop.create_task(fn())

    async def dismiss(self) -> None:
        if self._msg:
            await self._msg.delete()

    async def _edit_text(self, text: str, **kwargs: Any) -> None:
        try:
            if self._msg is None:
                self._msg = await self._user_msg.reply_text(text, **kwargs)
            else:
                if self._msg.text != text:
                    await self._msg.edit_text(text, **kwargs)
        except (FloodWait, SlowmodeWait):
            pass
        except Forbidden as e:
            logger.warning(f"消息发送失败, Bot 无权限: {e}")


class InlineStatusReporter(StatusReporter):
    """基于 inline_message_id 的状态报告器"""

    def __init__(
        self,
        cli: Client,
        inline_message_id: str,
        caption: str = "",
        *,
        _t: PreLocaleSelector,
        user_config: SettingsConfig,
    ):
        self._cli = cli
        self._mid = inline_message_id
        self._caption = caption
        self._last_text: str | None = None
        self._t = _t
        self._user_config = user_config

    async def report(self, text: str) -> None:
        text = format_label(text)
        full = f"{self._caption}\n{text}" if self._caption else text
        if full == self._last_text:
            return
        self._last_text = full
        await self._edit_inline_text(inline_message_id=self._mid, text=full)

    async def report_error(self, stage: str, error: Exception) -> None:
        text = self._t(f"{format_label(f'{stage}错误:')} \n```\n{error}```")
        if bs.demo_mode:
            text += self._t("\n\n**问题反馈: @MisakaSisters**")
        await self._edit_inline_text(
            inline_message_id=self._mid, text=text, link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        if self._user_config.keep_error_log:
            return

        async def fn() -> None:
            await asyncio.sleep(15)
            await self._edit_inline_text(
                inline_message_id=self._mid,
                text=self._caption,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )

        loop = asyncio.get_running_loop()
        loop.create_task(fn())

    async def _edit_inline_text(self, **kwargs: Any) -> None:
        try:
            await self._cli.edit_inline_text(**kwargs)
        except (FloodWait, SlowmodeWait):
            pass
        except Forbidden as e:
            logger.warning(f"消息发送失败, Bot 无权限: {e}")

    async def dismiss(self) -> None:
        pass
