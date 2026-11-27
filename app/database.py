"""SQLite 本地持久化层：会话、消息、多 API 配置、设置与人设."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from app.paths import get_db_path
from app.providers import DEFAULT_PERSONAS, DEFAULT_PROVIDERS
from app.security import decrypt_secret, encrypt_secret, mask_secret

DEFAULT_SETTINGS: dict[str, Any] = {
    "active_provider_id": "kimi_cli",
    "active_model": "default",
    "active_mode": "work",  # work | chat
    "sidebar_open": True,
    "work_memory_mode": "session",  # none | session | long_term
    "chat_memory_mode": "long_term",  # none | session | long_term
    "active_project_dir": "",
    "recent_projects": [],
    "permission_level": "standard",  # readonly | standard | full
    "kimi_cli_path": "",
    "active_persona_id": "assistant",
    "active_skin_id": "godzilla",
    "theme": "light",
    "web_search_enabled": False,
    "thinking_enabled": False,
    "reasoning_effort": "medium",
    "pet_scale": 100,
    "pet_opacity": 100,
    "dialog_width": 496,
    "dialog_max_height": 400,
    "dialog_font_size": 11.5,
    "pet_always_on_top": False,
    "pet_edge_hide": True,
    "pet_auto_walk": True,
    "pet_idle_bubbles": True,
    "pet_idle_interval_sec": 10,
    "pet_walk_duration_sec": 4,
    "pet_sleep_timeout_min": 10,
    "pet_bubble_duration_sec": 4,
    "care_poll_interval_sec": 60,
    "ai_timeout_sec": 180,
    "reminder_enabled": False,
    "reminder_interval_min": 45,
    "reminder_daily_time": "",
    "reminder_text": "已经专注一段时间啦，起来活动一下、喝口水吧",
    "eat_moves_to_recycle_bin": False,
    "launch_at_startup": False,
    "hotkey_toggle": "Alt+Space",
    "hotkey_screenshot": "Alt+S",
    "user_memory": "",
    "work_memory": "",
    "chat_memory": "",
    "fallback_search_provider": "none",  # none | tavily | bocha
    "fallback_search_api_key_enc": "",
    "onboarding_completed": False,
}


class Database:
    def __init__(self) -> None:
        self._path = get_db_path()
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key_enc TEXT NOT NULL DEFAULT '',
                    default_model TEXT NOT NULL DEFAULT '',
                    models_json TEXT NOT NULL DEFAULT '[]',
                    supports_web_search INTEGER NOT NULL DEFAULT 0,
                    supports_files_api INTEGER NOT NULL DEFAULT 0,
                    supports_thinking INTEGER NOT NULL DEFAULT 1,
                    supports_vision INTEGER NOT NULL DEFAULT 1,
                    is_kimi INTEGER NOT NULL DEFAULT 0,
                    is_custom INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS personas (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    icon TEXT NOT NULL DEFAULT '✨',
                    prompt TEXT NOT NULL,
                    is_custom INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    provider_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    persona_id TEXT NOT NULL DEFAULT 'assistant',
                    cli_session_id TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'work',
                    project_dir TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    reasoning TEXT NOT NULL DEFAULT '',
                    reasoning_seconds REAL NOT NULL DEFAULT 0,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    model TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv
                    ON messages(conversation_id, created_at);
                """
            )
            # 兼容旧库平滑补充 cli_session_id / mode / project_dir 列
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
            if "cli_session_id" not in cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN cli_session_id TEXT NOT NULL DEFAULT ''")
            if "mode" not in cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'work'")
            if "project_dir" not in cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN project_dir TEXT NOT NULL DEFAULT ''")
            msg_cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
            if "steps_json" not in msg_cols:
                conn.execute("ALTER TABLE messages ADD COLUMN steps_json TEXT NOT NULL DEFAULT '[]'")

            # v1.2.5 一次性迁移：将既有用户的默认置顶切换为「只在桌面显示（不遮挡其他软件窗口）」
            mig_row = conn.execute(
                "SELECT value FROM settings WHERE key = '_migrated_desktop_only_v125'"
            ).fetchone()
            if not mig_row:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('pet_always_on_top', 'false') "
                    "ON CONFLICT(key) DO UPDATE SET value = 'false'"
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('_migrated_desktop_only_v125', 'true') "
                    "ON CONFLICT(key) DO UPDATE SET value = 'true'"
                )

            # v1.3.0 一次性迁移：自动为既有用户切换至全新巨型哥斯拉皮肤（随时可在右键菜单切回小狐狸/轻音少女）
            mig_gz = conn.execute(
                "SELECT value FROM settings WHERE key = '_migrated_godzilla_skin_v130'"
            ).fetchone()
            if not mig_gz:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('active_skin_id', '\"godzilla\"') "
                    "ON CONFLICT(key) DO UPDATE SET value = '\"godzilla\"'"
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('_migrated_godzilla_skin_v130', 'true') "
                    "ON CONFLICT(key) DO UPDATE SET value = 'true'"
                )

            now = time.time()
            # 仅保留 Kimi 专属通道，自动清理旧版本残留的其他供应商
            valid_ids = tuple(p["id"] for p in DEFAULT_PROVIDERS)
            placeholders = ",".join("?" for _ in valid_ids)
            conn.execute(f"DELETE FROM providers WHERE id NOT IN ({placeholders})", valid_ids)

            # 初始化 Kimi 供应商
            for p in DEFAULT_PROVIDERS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO providers (
                        id, name, base_url, api_key_enc, default_model, models_json,
                        supports_web_search, supports_files_api, supports_thinking,
                        supports_vision, is_kimi, is_custom, updated_at
                    ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["id"],
                        p["name"],
                        p["base_url"],
                        p["default_model"],
                        json.dumps(p["models"], ensure_ascii=False),
                        int(p["supports_web_search"]),
                        int(p["supports_files_api"]),
                        int(p["supports_thinking"]),
                        int(p["supports_vision"]),
                        int(p["is_kimi"]),
                        1 if p["id"] == "custom" else 0,
                        now,
                    ),
                )

            # 初始化默认人设
            for persona in DEFAULT_PERSONAS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO personas (id, name, icon, prompt, is_custom)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (persona["id"], persona["name"], persona["icon"], persona["prompt"]),
                )

            # 初始化默认设置
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, json.dumps(v, ensure_ascii=False)),
                )

    # ---------- Settings ----------

    def get_settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        data = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                data[row["key"]] = json.loads(row["value"])
            except Exception:
                data[row["key"]] = row["value"]
        # 脱敏返回外部搜索 Key
        raw_search_key = decrypt_secret(str(data.get("fallback_search_api_key_enc", "")))
        data["has_fallback_search_key"] = bool(raw_search_key)
        data["fallback_search_key_masked"] = mask_secret(raw_search_key)
        data.pop("fallback_search_api_key_enc", None)
        # 兼容旧配置：若之前填写了通用 user_memory 而未填写拆分记忆，自动继承
        legacy_mem = str(data.get("user_memory") or "").strip()
        if legacy_mem and not str(data.get("work_memory") or "").strip() and not str(data.get("chat_memory") or "").strip():
            data["work_memory"] = legacy_mem
            data["chat_memory"] = legacy_mem
        # 兼容旧配置：若之前停留在已移除的非 Kimi 通道，自动切回 kimi_cli
        if data.get("active_provider_id") not in ("kimi_cli", "kimi_cn"):
            data["active_provider_id"] = "kimi_cli"
            data["active_model"] = "default"
        return data

    def get_fallback_search_key(self) -> str:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'fallback_search_api_key_enc'"
            ).fetchone()
        if not row:
            return ""
        try:
            enc = json.loads(row["value"])
        except Exception:
            enc = row["value"]
        return decrypt_secret(str(enc))

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            for k, v in updates.items():
                if k == "fallback_search_api_key":
                    enc = encrypt_secret(str(v or "").strip())
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                        ("fallback_search_api_key_enc", json.dumps(enc)),
                    )
                    continue
                if k in ("has_fallback_search_key", "fallback_search_key_masked"):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (k, json.dumps(v, ensure_ascii=False)),
                )
        return self.get_settings()

    # ---------- Providers ----------

    def list_providers(self, include_raw_key: bool = False) -> list[dict[str, Any]]:
        preset_map = {p["id"]: p for p in DEFAULT_PROVIDERS}
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM providers").fetchall()
        order = {p["id"]: idx for idx, p in enumerate(DEFAULT_PROVIDERS)}
        results: list[dict[str, Any]] = []
        for row in rows:
            raw_key = decrypt_secret(row["api_key_enc"])
            preset = preset_map.get(row["id"], {})
            item = {
                "id": row["id"],
                "name": row["name"],
                "badge": preset.get("badge", "自定义"),
                "base_url": row["base_url"],
                "has_api_key": bool(raw_key),
                "api_key_masked": mask_secret(raw_key),
                "default_model": row["default_model"],
                "models": json.loads(row["models_json"] or "[]"),
                "supports_web_search": bool(row["supports_web_search"]),
                "supports_files_api": bool(row["supports_files_api"]),
                "supports_thinking": bool(row["supports_thinking"]),
                "supports_vision": bool(row["supports_vision"]),
                "is_kimi": bool(row["is_kimi"]),
                "is_custom": bool(row["is_custom"]),
                "key_url": preset.get("key_url", ""),
                "key_hint": preset.get("key_hint", ""),
            }
            if include_raw_key:
                item["api_key"] = raw_key
            results.append(item)
        results.sort(key=lambda x: (order.get(x["id"], 999), x["name"]))
        return results

    def get_provider(self, provider_id: str, include_raw_key: bool = False) -> dict[str, Any] | None:
        for item in self.list_providers(include_raw_key=include_raw_key):
            if item["id"] == provider_id:
                return item
        return None

    def save_provider(self, provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
            now = time.time()
            if existing:
                api_key_enc = existing["api_key_enc"]
                if "api_key" in data and data["api_key"] is not None:
                    # 只有显式传入新密钥时才覆盖；传空字符串代表清空
                    api_key_enc = encrypt_secret(str(data["api_key"]).strip())
                models = data.get("models")
                models_json = (
                    json.dumps(models, ensure_ascii=False)
                    if isinstance(models, list)
                    else existing["models_json"]
                )
                conn.execute(
                    """
                    UPDATE providers
                    SET name = ?, base_url = ?, api_key_enc = ?, default_model = ?,
                        models_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        data.get("name", existing["name"]),
                        str(data.get("base_url", existing["base_url"])).strip().rstrip("/"),
                        api_key_enc,
                        str(data.get("default_model", existing["default_model"])).strip(),
                        models_json,
                        now,
                        provider_id,
                    ),
                )
            else:
                api_key_enc = encrypt_secret(str(data.get("api_key", "")).strip())
                models = data.get("models") or []
                default_model = str(data.get("default_model", "")).strip()
                if default_model and default_model not in models:
                    models = [default_model] + models
                conn.execute(
                    """
                    INSERT INTO providers (
                        id, name, base_url, api_key_enc, default_model, models_json,
                        supports_web_search, supports_files_api, supports_thinking,
                        supports_vision, is_kimi, is_custom, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1, 1, 0, 1, ?)
                    """,
                    (
                        provider_id,
                        data.get("name") or "自定义供应商",
                        str(data.get("base_url", "")).strip().rstrip("/"),
                        api_key_enc,
                        default_model,
                        json.dumps(models, ensure_ascii=False),
                        now,
                    ),
                )
        result = self.get_provider(provider_id)
        assert result is not None
        return result

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM providers WHERE id = ? AND is_custom = 1 AND id != 'custom'",
                (provider_id,),
            )
            return cur.rowcount > 0

    # ---------- Personas ----------

    def list_personas(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM personas ORDER BY is_custom ASC, rowid ASC").fetchall()
        return [dict(r) for r in rows]

    def save_persona(self, persona: dict[str, Any]) -> dict[str, Any]:
        pid = persona.get("id") or f"custom_{uuid.uuid4().hex[:8]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO personas (id, name, icon, prompt, is_custom)
                VALUES (?, ?, ?, ?, 1)
                """,
                (pid, persona["name"], persona.get("icon", "🎭"), persona["prompt"]),
            )
        return {
            "id": pid,
            "name": persona["name"],
            "icon": persona.get("icon", "🎭"),
            "prompt": persona["prompt"],
            "is_custom": 1,
        }

    def delete_persona(self, persona_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM personas WHERE id = ? AND is_custom = 1", (persona_id,))
            return cur.rowcount > 0

    # ---------- Conversations & Messages ----------

    def list_conversations(self, query: str = "", mode: str = "") -> list[dict[str, Any]]:
        clean_mode = mode.strip().lower()
        with self._lock, self._connect() as conn:
            if query.strip():
                like = f"%{query.strip()}%"
                if clean_mode in ("chat", "work"):
                    rows = conn.execute(
                        """
                        SELECT DISTINCT c.* FROM conversations c
                        LEFT JOIN messages m ON m.conversation_id = c.id
                        WHERE c.mode = ? AND (c.title LIKE ? OR m.content LIKE ?)
                        ORDER BY c.pinned DESC, c.updated_at DESC
                        """,
                        (clean_mode, like, like),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT c.* FROM conversations c
                        LEFT JOIN messages m ON m.conversation_id = c.id
                        WHERE c.title LIKE ? OR m.content LIKE ?
                        ORDER BY c.pinned DESC, c.updated_at DESC
                        """,
                        (like, like),
                    ).fetchall()
            elif clean_mode in ("chat", "work"):
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE mode = ? ORDER BY pinned DESC, updated_at DESC",
                    (clean_mode,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM conversations ORDER BY pinned DESC, updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def create_conversation(
        self,
        title: str = "新对话",
        provider_id: str = "",
        model: str = "",
        persona_id: str = "assistant",
        mode: str = "work",
        project_dir: str = "",
    ) -> dict[str, Any]:
        cid = uuid.uuid4().hex
        now = time.time()
        clean_mode = "chat" if str(mode).lower() == "chat" else "work"
        clean_proj = "" if clean_mode == "chat" else str(project_dir or "")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    id, title, pinned, provider_id, model, persona_id, mode, project_dir, created_at, updated_at
                )
                VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cid, title, provider_id, model, persona_id, clean_mode, clean_proj, now, now),
            )
        return {
            "id": cid,
            "title": title,
            "pinned": 0,
            "provider_id": provider_id,
            "model": model,
            "persona_id": persona_id,
            "cli_session_id": "",
            "mode": clean_mode,
            "project_dir": clean_proj,
            "created_at": now,
            "updated_at": now,
        }

    def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return dict(row) if row else None

    def update_conversation(self, conv_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "pinned", "provider_id", "model", "persona_id", "cli_session_id", "mode", "project_dir"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_conversation(conv_id)
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [conv_id]
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE conversations SET {set_clause} WHERE id = ?", values)
        return self.get_conversation(conv_id)

    def delete_conversation(self, conv_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cur.rowcount > 0

    def clear_all_conversations(self, mode: str = "") -> None:
        clean_mode = mode.strip().lower()
        with self._lock, self._connect() as conn:
            if clean_mode in ("chat", "work"):
                conn.execute("DELETE FROM conversations WHERE mode = ?", (clean_mode,))
            else:
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")

    def list_messages(self, conv_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "id": r["id"],
                    "conversation_id": r["conversation_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "reasoning": r["reasoning"],
                    "reasoning_seconds": r["reasoning_seconds"],
                    "sources": json.loads(r["sources_json"] or "[]"),
                    "attachments": json.loads(r["attachments_json"] or "[]"),
                    "steps": json.loads(r["steps_json"] or "[]") if "steps_json" in r.keys() else [],
                    "model": r["model"],
                    "created_at": r["created_at"],
                }
            )
        return items

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        reasoning: str = "",
        reasoning_seconds: float = 0.0,
        sources: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        steps: list[dict[str, Any]] | None = None,
        model: str = "",
    ) -> dict[str, Any]:
        mid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, reasoning, reasoning_seconds,
                    sources_json, attachments_json, steps_json, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    conv_id,
                    role,
                    content,
                    reasoning,
                    reasoning_seconds,
                    json.dumps(sources or [], ensure_ascii=False),
                    json.dumps(attachments or [], ensure_ascii=False),
                    json.dumps(steps or [], ensure_ascii=False),
                    model,
                    now,
                ),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
        return {
            "id": mid,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "reasoning": reasoning,
            "reasoning_seconds": reasoning_seconds,
            "sources": sources or [],
            "attachments": attachments or [],
            "steps": steps or [],
            "model": model,
            "created_at": now,
        }

    def delete_messages_from(self, conv_id: str, message_id: str) -> None:
        """用于编辑/重试：删除指定消息及之后的消息."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id = ? AND conversation_id = ?",
                (message_id, conv_id),
            ).fetchone()
            if not row:
                return
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND created_at >= ?",
                (conv_id, row["created_at"]),
            )
