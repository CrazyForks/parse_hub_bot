from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import batched
from typing import Literal, Self, cast

from parsehub.types import Platform
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle, ChatType
from pyrogram.types import CallbackQuery, Message
from pyrogram.types import InlineKeyboardButton as Ikb
from pyrogram.types import InlineKeyboardMarkup as Ikm

from db import get_session
from db.models.settings import SettingsScope
from i18n import LANG_MAP, t_
from repo.settings import DefaultMode, SettingsConfig
from repo.settings.schema import ConfigMetadata
from services import SettingsService, UserService
from services.settings import (
    AnySettingsTarget,
    ChannelSettingsTarget,
    ForumTopicMemberSettingsTarget,
    ForumTopicSettingsTarget,
    GroupMemberSettingsTarget,
    GroupSettingsTarget,
    UserSettingsTarget,
)


@dataclass
class CQData:
    key: str
    """键放在最前面, 可用 filters.regex(r"^key") 过滤"""
    value: str
    """值"""
    uid: int
    """user id"""

    @classmethod
    def parse(cls, data: str | bytes) -> Self:
        key, value, uid = str(data).split(",")
        return cls(key=key, value=value, uid=int(uid))

    def unparse(self) -> str:
        return f"{self.key},{self.value},{self.uid}"

    def __str__(self) -> str:
        return self.unparse()

    def __repr__(self) -> str:
        return self.__str__()


CfgAction = Literal["t", "m", "b", "p", "o"]
CfgScopeCode = Literal["u", "g", "gm", "ft", "ftm", "c"]
CfgPage = Literal["main", "platform"]
BoolSwitchField = Literal["enable_inline_raw_url", "keep_error_log", "hide_source", "noprogress", "auto_delete_url"]


@dataclass(frozen=True, slots=True)
class CfgCQData:
    action: CfgAction
    value: str
    scope: CfgScopeCode | None = None
    channel_id: int | None = None

    @classmethod
    def parse(cls, data: str | bytes) -> Self:
        parts = str(data).split("|")
        _, action, value, *rest = parts
        scope = cast(CfgScopeCode, rest[0]) if rest else None
        channel_id = int(rest[1]) if len(rest) > 1 else None
        return cls(action=cast(CfgAction, action), value=value, scope=scope, channel_id=channel_id)

    def unparse(self) -> str:
        parts = ["cfg", self.action, self.value]
        if self.scope:
            parts.append(self.scope)
        if self.channel_id:
            parts.append(str(self.channel_id))
        return "|".join(parts)


@dataclass(frozen=True, slots=True)
class CfgTargetOption:
    label: str
    scope: CfgScopeCode
    target: AnySettingsTarget


@dataclass(frozen=True, slots=True)
class SettingsViewModel:
    config: SettingsConfig
    target: AnySettingsTarget | None
    allowed_fields: frozenset[str]
    target_label: str | None
    target_options: tuple[CfgTargetOption, ...] = ()


@dataclass(frozen=True, slots=True)
class BoolSwitchDTO:
    field: BoolSwitchField
    code: str
    label: str
    get_value: Callable[[SettingsConfig], bool]
    patch: Callable[[SettingsService, AnySettingsTarget, bool], Awaitable[SettingsConfig]]


MODE_MAP = {
    "preview": t_("预览"),
    "raw": t_("原始"),
    "zip": t_("压缩"),
}

BOOL_SWITCHES = (
    BoolSwitchDTO(
        field="enable_inline_raw_url",
        code="ir",
        label="内联发送原始 URL 选项",
        get_value=lambda config: config.enable_inline_raw_url,
        patch=lambda settings, target, value: settings.patch_config(target, enable_inline_raw_url=value),
    ),
    BoolSwitchDTO(
        field="keep_error_log",
        code="el",
        label="保留错误日志",
        get_value=lambda config: config.keep_error_log,
        patch=lambda settings, target, value: settings.patch_config(target, keep_error_log=value),
    ),
    BoolSwitchDTO(
        field="hide_source",
        code="hs",
        label="隐藏底部 Source 超链接",
        get_value=lambda config: config.hide_source,
        patch=lambda settings, target, value: settings.patch_config(target, hide_source=value),
    ),
    BoolSwitchDTO(
        field="noprogress",
        code="np",
        label="隐藏解析进度",
        get_value=lambda config: config.noprogress,
        patch=lambda settings, target, value: settings.patch_config(target, noprogress=value),
    ),
    BoolSwitchDTO(
        field="auto_delete_url",
        code="ad",
        label="自动删除链接消息",
        get_value=lambda config: config.auto_delete_url,
        patch=lambda settings, target, value: settings.patch_config(target, auto_delete_url=value),
    ),
)

BOOL_SWITCH_MAP = {switch.code: switch for switch in BOOL_SWITCHES}


@Client.on_message(filters.command("lang"))
async def select_lang(_: Client, msg: Message) -> None:
    if not msg.from_user:
        return

    async with get_session() as session:
        lang = await UserService(session).get_lang(msg.from_user.id)

    ikbs = [
        Ikb(
            v,
            callback_data=CQData(key="lang", value=k, uid=msg.from_user.id).unparse(),
            style=ButtonStyle.PRIMARY if k == lang else ButtonStyle.DEFAULT,
        )
        for k, v in LANG_MAP.items()
    ]

    reply_markup = Ikm([ikbs[i : i + 2] for i in range(0, len(ikbs), 2)])
    await msg.reply_text("**▎选择语言 / Select Language**", reply_markup=reply_markup)


@Client.on_callback_query(filters.regex(r"^lang"))
async def selected_lang(_: Client, cq: CallbackQuery) -> None:
    if not cq.data:
        return

    cqdata = CQData.parse(cq.data)
    if not await ensure_callback_owner(cq, cqdata.uid):
        return

    selected = cqdata.value
    async with get_session() as session:
        user = await UserService(session).set_lang(cq.from_user.id, selected)

    await cq.message.edit(t_[user.language_code](f"**▎已切换为: {LANG_MAP[selected]}**"))


@Client.on_message(filters.command("cfg"))
async def cfg(client: Client, msg: Message) -> None:
    if not msg.from_user:
        return

    async with get_session() as session:
        lang = await UserService(session).get_lang(msg.from_user.id)

    channel_ref = parse_cfg_arg(msg.text or "")
    if channel_ref:
        target = await resolve_channel_target(client, msg, lang, channel_ref)
        if not target:
            return
        async with get_session() as session:
            vm = await build_cfg_vm(SettingsService(session), lang, target, "频道配置")
        await msg.reply(t_[lang]("**▎配置面板 - 频道配置**"), reply_markup=build_cfg_markup(lang, vm))
        return

    options = await build_cfg_target_options(client, msg, lang)
    if not options:
        return

    if len(options) == 1:
        option = options[0]
        async with get_session() as session:
            vm = await build_cfg_vm(SettingsService(session), lang, option.target, option.label)
        await msg.reply(t_[lang](f"**▎配置面板 - {option.label}**"), reply_markup=build_cfg_markup(lang, vm))
        return

    vm = SettingsViewModel(
        config=SettingsConfig(),
        target=None,
        allowed_fields=frozenset(),
        target_label=None,
        target_options=tuple(options),
    )
    await msg.reply(t_[lang]("**▎选择配置目标**"), reply_markup=build_cfg_markup(lang, vm))


@Client.on_callback_query(filters.regex(r"^cfg"))
async def cfg_callback(client: Client, cq: CallbackQuery) -> None:
    if not cq.data or not cq.message:
        return

    data = CfgCQData.parse(cq.data)
    async with get_session() as session:
        lang = await UserService(session).get_lang(cq.from_user.id)

    target = restore_cfg_target(cq, data)
    if not target:
        await cq.answer(t_[lang]("无法识别配置目标"), show_alert=True)
        return

    if not await ensure_cfg_permission(client, cq, lang, target):
        return

    async with get_session() as session:
        settings = SettingsService(session)
        match data.action:
            case "t":
                pass
            case "m":
                selected = cast(DefaultMode, data.value)
                if not await ensure_cfg_field(cq, lang, target, "default_mode"):
                    return
                await settings.patch_config(target, default_mode=selected)
            case "b":
                switch = BOOL_SWITCH_MAP.get(data.value)
                if not switch:
                    await cq.answer(t_[lang]("未知配置项"), show_alert=True)
                    return
                if not await ensure_cfg_field(cq, lang, target, switch.field):
                    return
                config = await settings.get_config(target)
                await switch.patch(settings, target, not switch.get_value(config))
            case "p":
                if not await ensure_cfg_field(cq, lang, target, "disabled_platforms"):
                    return
                config = await settings.get_config(target)
                disabled_platforms = config.disabled_platforms.copy()
                if data.value in disabled_platforms:
                    disabled_platforms.remove(data.value)
                else:
                    disabled_platforms.append(data.value)
                await settings.patch_config(target, disabled_platforms=disabled_platforms)
            case "o":
                pass

        label = cfg_target_label(lang, target)
        vm = await build_cfg_vm(settings, lang, target, label)

    page: CfgPage = "platform" if (data.action == "p" or data.value == "p") else "main"
    await cq.message.edit(t_[lang](f"**▎配置面板 - {vm.target_label}**"), reply_markup=build_cfg_markup(lang, vm, page))


def build_cfg_markup(lang: str, vm: SettingsViewModel, page: CfgPage = "main") -> Ikm:
    if vm.target is None:
        return build_cfg_target_markup(vm)
    if page == "platform":
        return build_cfg_platform_markup(vm)
    return build_cfg_main_markup(lang, vm)


def build_cfg_target_markup(vm: SettingsViewModel) -> Ikm:
    return Ikm(
        [
            [
                Ikb(
                    option.label,
                    callback_data=CfgCQData(
                        action="t",
                        value="main",
                        scope=option.scope,
                        channel_id=get_cfg_channel_id(option.target),
                    ).unparse(),
                )
            ]
            for option in vm.target_options
        ]
    )


def build_cfg_main_markup(lang: str, vm: SettingsViewModel) -> Ikm:
    rows: list[list[Ikb]] = []

    if "default_mode" in vm.allowed_fields:
        rows.append(
            [
                Ikb(
                    label[lang],
                    callback_data=cfg_callback_data("m", value, vm.target),
                    style=ButtonStyle.PRIMARY if value == vm.config.default_mode else ButtonStyle.DEFAULT,
                )
                for value, label in MODE_MAP.items()
            ]
        )

    switches = [switch for switch in BOOL_SWITCHES if switch.field in vm.allowed_fields]
    buttons = [
        Ikb(
            t_[lang](switch.label),
            callback_data=cfg_callback_data("b", switch.code, vm.target),
            style=reply_bool_style(switch.get_value(vm.config)),
        )
        for switch in switches
    ]
    rows.extend([list(row) for row in batched(buttons, 2)])

    if "disabled_platforms" in vm.allowed_fields:
        rows.append([Ikb(t_[lang]("管理平台解析"), callback_data=cfg_callback_data("o", "p", vm.target))])

    return Ikm(rows)


def build_cfg_platform_markup(vm: SettingsViewModel) -> Ikm:
    ikbs = [
        Ikb(
            p.display_name,
            callback_data=cfg_callback_data("p", p.id, vm.target),
            style=ButtonStyle.DANGER if p.id in vm.config.disabled_platforms else ButtonStyle.SUCCESS,
        )
        for p in list(Platform)
    ]
    rows = [list(row) for row in batched(ikbs, 2)]
    rows.append([Ikb("返回配置页", callback_data=cfg_callback_data("o", "main", vm.target))])
    return Ikm(rows)


def reply_bool_style(v: bool) -> ButtonStyle:
    return ButtonStyle.SUCCESS if v else ButtonStyle.DANGER


def cfg_callback_data(action: CfgAction, value: str, target: AnySettingsTarget | None) -> str:
    return CfgCQData(
        action=action,
        value=value,
        scope=cfg_scope_code(target),
        channel_id=get_cfg_channel_id(target),
    ).unparse()


async def build_cfg_vm(
    settings: SettingsService, lang: str, target: AnySettingsTarget, target_label: str
) -> SettingsViewModel:
    return SettingsViewModel(
        config=await settings.get_config(target),
        target=target,
        allowed_fields=get_allowed_fields(target.scope),
        target_label=t_[lang](target_label),
    )


async def build_cfg_target_options(client: Client, msg: Message, lang: str) -> list[CfgTargetOption]:
    if not msg.from_user or not msg.chat:
        return []

    chat_id = msg.chat.id
    if chat_id is None:
        return []
    thread_id = get_message_thread_id(msg)
    if msg.chat.type == ChatType.PRIVATE:
        return [CfgTargetOption(t_[lang]("个人配置"), "u", UserSettingsTarget(telegram_user_id=msg.from_user.id))]

    if msg.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await msg.reply(t_[lang]("请在私聊、群组、话题或使用 /cfg <频道> 配置。"))
        return []

    is_admin = await is_chat_admin(client, chat_id, msg.from_user.id)
    if thread_id:
        if is_admin:
            return [
                CfgTargetOption(t_[lang]("个人配置"), "u", UserSettingsTarget(telegram_user_id=msg.from_user.id)),
                CfgTargetOption(
                    t_[lang]("话题个人配置"),
                    "ftm",
                    ForumTopicMemberSettingsTarget(
                        telegram_chat_id=chat_id,
                        telegram_thread_id=thread_id,
                        telegram_user_id=msg.from_user.id,
                    ),
                ),
                CfgTargetOption(
                    t_[lang]("话题配置"),
                    "ft",
                    ForumTopicSettingsTarget(telegram_chat_id=chat_id, telegram_thread_id=thread_id),
                ),
            ]
        return [
            CfgTargetOption(
                t_[lang]("话题个人配置"),
                "ftm",
                ForumTopicMemberSettingsTarget(
                    telegram_chat_id=chat_id,
                    telegram_thread_id=thread_id,
                    telegram_user_id=msg.from_user.id,
                ),
            )
        ]

    if is_admin:
        return [
            CfgTargetOption(t_[lang]("个人配置"), "u", UserSettingsTarget(telegram_user_id=msg.from_user.id)),
            CfgTargetOption(
                t_[lang]("群组个人配置"),
                "gm",
                GroupMemberSettingsTarget(telegram_chat_id=chat_id, telegram_user_id=msg.from_user.id),
            ),
            CfgTargetOption(t_[lang]("群组配置"), "g", GroupSettingsTarget(telegram_chat_id=chat_id)),
        ]
    return [
        CfgTargetOption(
            t_[lang]("群组个人配置"),
            "gm",
            GroupMemberSettingsTarget(telegram_chat_id=chat_id, telegram_user_id=msg.from_user.id),
        )
    ]


def restore_cfg_target(cq: CallbackQuery, data: CfgCQData) -> AnySettingsTarget | None:
    if not data.scope or not cq.message or not cq.message.chat:
        return None

    chat_id = cq.message.chat.id
    if chat_id is None:
        return None
    match data.scope:
        case "u":
            return UserSettingsTarget(telegram_user_id=cq.from_user.id)
        case "g":
            return GroupSettingsTarget(telegram_chat_id=chat_id)
        case "gm":
            return GroupMemberSettingsTarget(telegram_chat_id=chat_id, telegram_user_id=cq.from_user.id)
        case "ft":
            thread_id = get_message_thread_id(cq.message)
            if not thread_id:
                return None
            return ForumTopicSettingsTarget(telegram_chat_id=chat_id, telegram_thread_id=thread_id)
        case "ftm":
            thread_id = get_message_thread_id(cq.message)
            if not thread_id:
                return None
            return ForumTopicMemberSettingsTarget(
                telegram_chat_id=chat_id,
                telegram_thread_id=thread_id,
                telegram_user_id=cq.from_user.id,
            )
        case "c":
            if data.channel_id is None:
                return None
            return ChannelSettingsTarget(telegram_chat_id=data.channel_id)


def cfg_scope_code(target: AnySettingsTarget | None) -> CfgScopeCode | None:
    match target:
        case UserSettingsTarget():
            return "u"
        case GroupSettingsTarget():
            return "g"
        case GroupMemberSettingsTarget():
            return "gm"
        case ForumTopicSettingsTarget():
            return "ft"
        case ForumTopicMemberSettingsTarget():
            return "ftm"
        case ChannelSettingsTarget():
            return "c"
        case None:
            return None


def get_cfg_channel_id(target: AnySettingsTarget | None) -> int | None:
    if isinstance(target, ChannelSettingsTarget):
        return target.telegram_chat_id
    return None


def cfg_target_label(lang: str, target: AnySettingsTarget) -> str:
    match target:
        case UserSettingsTarget():
            return cast(str, t_[lang]("个人配置"))
        case GroupSettingsTarget():
            return cast(str, t_[lang]("群组配置"))
        case GroupMemberSettingsTarget():
            return cast(str, t_[lang]("群组个人配置"))
        case ForumTopicSettingsTarget():
            return cast(str, t_[lang]("话题配置"))
        case ForumTopicMemberSettingsTarget():
            return cast(str, t_[lang]("话题个人配置"))
        case ChannelSettingsTarget():
            return cast(str, t_[lang]("频道配置"))


def get_allowed_fields(scope: SettingsScope) -> frozenset[str]:
    fields = []
    for field_name, field in SettingsConfig.model_fields.items():
        for metadata in field.metadata:
            if isinstance(metadata, ConfigMetadata) and scope in metadata.scopes:
                fields.append(field_name)
                break
    return frozenset(fields)


async def ensure_cfg_field(cq: CallbackQuery, lang: str, target: AnySettingsTarget, field_name: str) -> bool:
    if field_name not in get_allowed_fields(target.scope):
        await cq.answer(t_[lang]("当前配置目标不支持这个配置项"), show_alert=True)
        return False
    return True


async def ensure_cfg_permission(client: Client, cq: CallbackQuery, lang: str, target: AnySettingsTarget) -> bool:
    match target:
        case UserSettingsTarget():
            return True
        case GroupMemberSettingsTarget() | ForumTopicMemberSettingsTarget():
            return True
        case GroupSettingsTarget(telegram_chat_id=chat_id) | ForumTopicSettingsTarget(telegram_chat_id=chat_id):
            if await is_chat_admin(client, chat_id, cq.from_user.id):
                return True
            await cq.answer(t_[lang]("你不是该聊天的管理员，无权修改配置。"), show_alert=True)
            return False
        case ChannelSettingsTarget(telegram_chat_id=chat_id):
            if await is_chat_owner(client, chat_id, cq.from_user.id):
                return True
            await cq.answer(t_[lang]("你不是该频道的拥有者，无权修改频道配置。"), show_alert=True)
            return False


async def resolve_channel_target(
    client: Client,
    msg: Message,
    lang: str,
    channel_ref: str,
) -> ChannelSettingsTarget | None:
    if not msg.from_user:
        return None

    try:
        chat = await client.get_chat(parse_channel_ref(channel_ref))
    except Exception:
        await msg.reply(t_[lang]("Bot 未加入该频道，请先将 Bot 加入频道后再配置。"))
        return None

    if chat.id is None:
        await msg.reply(t_[lang]("Bot 未加入该频道，请先将 Bot 加入频道后再配置。"))
        return None

    if not await is_chat_owner(client, chat.id, msg.from_user.id):
        await msg.reply(t_[lang]("你不是该频道的拥有者，无权修改频道配置。"))
        return None

    return ChannelSettingsTarget(telegram_chat_id=chat.id)


def parse_cfg_arg(text: str) -> str | None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


def parse_channel_ref(value: str) -> int | str:
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    if value.startswith("https://t.me/"):
        value = value.removeprefix("https://t.me/")
    elif value.startswith("http://t.me/"):
        value = value.removeprefix("http://t.me/")
    elif value.startswith("t.me/"):
        value = value.removeprefix("t.me/")
    if not value.startswith("@"):
        value = f"@{value}"
    return value


def get_message_thread_id(msg: Message) -> int | None:
    return cast(int | None, getattr(msg, "message_thread_id", None))


async def is_chat_admin(client: Client, chat_id: int | str, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return chat_member_status(member.status) in {"administrator", "owner", "creator"}


async def is_chat_owner(client: Client, chat_id: int | str, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return chat_member_status(member.status) in {"owner", "creator"}


def chat_member_status(status: object) -> str:
    return str(getattr(status, "value", status)).lower()


async def ensure_callback_owner(
    cq: CallbackQuery,
    owner_id: int,
) -> bool:
    if cq.from_user.id != owner_id:
        async with get_session() as session:
            lang = await UserService(session).get_lang(cq.from_user.id)
        await cq.answer(t_[lang]("这不是你的操作"), show_alert=True)
        return False
    return True
