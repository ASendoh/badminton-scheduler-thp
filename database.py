from __future__ import annotations

from typing import Any

import streamlit as st
from supabase import Client, create_client


TABLE_NAME = "usage_records"


class DatabaseConfigurationError(RuntimeError):
    """数据库密钥或地址没有正确配置。"""


class DatabaseOperationError(RuntimeError):
    """数据库读写失败。"""


def _database_settings() -> tuple[str, str]:
    try:
        url = str(st.secrets["supabase"]["url"]).strip()
        key = str(st.secrets["supabase"]["key"]).strip()
    except (FileNotFoundError, KeyError, TypeError) as exc:
        raise DatabaseConfigurationError(
            "缺少 [supabase] url 或 key。"
        ) from exc

    if not url or not key:
        raise DatabaseConfigurationError(
            "Supabase URL 或服务器端 Secret Key 为空。"
        )

    return url, key


@st.cache_resource
def get_database_client() -> Client:
    url, key = _database_settings()
    return create_client(url, key)


def save_usage_record(payload: dict[str, Any]) -> None:
    client = get_database_client()

    try:
        client.table(TABLE_NAME).insert(payload).execute()
        return
    except DatabaseConfigurationError:
        raise
    except Exception as first_exc:
        # 兼容尚未执行 V1.5 数据库迁移的旧表：先继续保存其他字段。
        if "fixed_partner" not in payload:
            raise DatabaseOperationError(str(first_exc)) from first_exc

        legacy_payload = payload.copy()
        legacy_payload.pop("fixed_partner", None)
        try:
            client.table(TABLE_NAME).insert(legacy_payload).execute()
            return
        except Exception as second_exc:
            raise DatabaseOperationError(str(second_exc)) from second_exc


def fetch_usage_records(limit: int = 1000) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    client = get_database_client()

    try:
        response = (
            client
            .table(TABLE_NAME)
            .select(
                "id,created_at,player_count,mode,rounds,"
                "exclude_male_vs_female,players,fixed_partner,app_version"
            )
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
    except DatabaseConfigurationError:
        raise
    except Exception:
        # 旧表还没有 fixed_partner 字段时，后台仍可读取既有记录。
        try:
            response = (
                client
                .table(TABLE_NAME)
                .select(
                    "id,created_at,player_count,mode,rounds,"
                    "exclude_male_vs_female,players,app_version"
                )
                .order("created_at", desc=True)
                .limit(safe_limit)
                .execute()
            )
        except Exception as exc:
            raise DatabaseOperationError(str(exc)) from exc

    data = response.data
    if not isinstance(data, list):
        return []

    return [
        item
        for item in data
        if isinstance(item, dict)
    ]
