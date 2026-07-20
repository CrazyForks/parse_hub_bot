from pyrogram import Client
from pyrogram.types import InlineQuery, Message


@Client.on_message(group=-1)
async def register(_: Client, msg: Message) -> None:
    print(msg)


@Client.on_inline_query(group=-1)
async def inline_register(_: Client, iq: InlineQuery) -> None:
    print(iq)
