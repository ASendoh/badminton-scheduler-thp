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
    try:
        (
            get_database_client()
            .table(TABLE_NAME)
            .insert(payload)
            .execute()
        )
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseOperationError(str(exc)) from exc


def fetch_usage_records(limit: int = 1000) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))

    try:
        response = (
            get_database_client()
            .table(TABLE_NAME)
            .select(
                "id,created_at,player_count,mode,rounds,"
                "exclude_male_vs_female,players,app_version"
            )
            .order("created_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
    except DatabaseConfigurationError:
        raise
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
