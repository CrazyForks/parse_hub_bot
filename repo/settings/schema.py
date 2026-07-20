from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from db.models.settings import SettingsScope

CURRENT_SCHEMA_VERSION = 3

DefaultMode = Literal["preview", "raw", "zip"]


@dataclass(frozen=True)
class ScopePolicy:
    allowed_scopes: frozenset[SettingsScope]


ALL_SCOPES = frozenset(SettingsScope)


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")  # 保留旧字段

    schema_version: Annotated[int, ScopePolicy(ALL_SCOPES), Field(ge=1, frozen=True)] = CURRENT_SCHEMA_VERSION
    default_mode: Annotated[DefaultMode, ScopePolicy(ALL_SCOPES), Field(description="默认解析模式")] = "preview"
    auto_delete_url: Annotated[bool, ScopePolicy(ALL_SCOPES), Field(description="解析完成后自动删除分享链接")] = False
    disabled_platforms: Annotated[list[str], ScopePolicy(ALL_SCOPES), Field(description="禁用的平台")] = []
    enable_inline_raw_url: Annotated[
        bool, ScopePolicy(frozenset([SettingsScope.USER])), Field(description="启用内联模式的发送原始 URL 功能")
    ] = False
    keep_error_log: Annotated[bool, ScopePolicy(ALL_SCOPES), Field(description="保留错误日志")] = False
    hide_source: Annotated[bool, ScopePolicy(ALL_SCOPES), Field(description="隐藏底部 Source 超链接")] = False
    noprogress: Annotated[bool, ScopePolicy(ALL_SCOPES), Field(description="禁用解析进度, 直接发送结果")] = False

    def __str__(self) -> str:
        return self.model_dump_json(indent=4, ensure_ascii=True)


DEFAULT_CONFIG = Config()
