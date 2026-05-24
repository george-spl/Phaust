"""SQLite-backed local memory store."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from phaust.memory.embeddings import pack_embedding, unpack_embedding
from phaust.memory.paths import (
    CONTEXT_FILE,
    DB_FILE,
    LEGACY_FILE,
    LONG_TERM_FILE,
    SEMANTIC_FILE,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    embedding BLOB,
    embedding_backend TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_id ON messages(id);
"""


@dataclass
class MemoryStore:
    db_path: Path = DB_FILE

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        self._migrate_json_if_needed()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _migrate_json_if_needed(self) -> None:
        if self.get_meta("json_migrated") == "1":
            return
        imported = False
        if CONTEXT_FILE.exists():
            self._import_context_json(CONTEXT_FILE)
            imported = True
        if LONG_TERM_FILE.exists():
            self._import_long_term_json(LONG_TERM_FILE)
            imported = True
        if SEMANTIC_FILE.exists():
            self._import_semantic_json(SEMANTIC_FILE)
            imported = True
        if LEGACY_FILE.exists():
            self._import_legacy_json(LEGACY_FILE)
            imported = True
        if imported:
            print("Imported legacy JSON memory into SQLite (Memory/phaust.db)")
        self.set_meta("json_migrated", "1")

    def _import_context_json(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for msg in data.get("messages", []):
            self.append_message(msg)
        for k, v in data.get("session", {}).items():
            self.set_session(k, v)

    def _import_long_term_json(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("facts", data)
        if not isinstance(raw, dict):
            return
        for key, entry in raw.items():
            if isinstance(entry, dict) and "value" in entry:
                self.upsert_fact(
                    key,
                    str(entry["value"]),
                    created_at=entry.get("created_at"),
                    updated_at=entry.get("updated_at"),
                )
            else:
                self.upsert_fact(key, str(entry))

    def _import_semantic_json(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("entries", []):
            emb = entry.get("embedding")
            blob = pack_embedding(emb) if emb else None
            self.insert_episode(
                entry_id=entry["id"],
                text=entry["text"],
                source=entry.get("source", "import"),
                tags=entry.get("tags", []),
                created_at=entry.get("created_at"),
                embedding=blob,
                embedding_backend=entry.get("embedding_backend"),
            )

    def _import_legacy_json(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not self.message_count():
            for msg in data.get("messages", []):
                self.append_message(msg)
        for key, value in data.get("memory", {}).items():
            self.upsert_fact(key, str(value))

    # ── meta ───────────────────────────────────────────────

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    # ── facts (long-term) ──────────────────────────────────

    def upsert_fact(
        self,
        key: str,
        value: str,
        *,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        created = created_at or now
        updated = updated_at or now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, created, updated),
            )
            conn.commit()

    def get_fact(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return dict(row)

    def delete_fact(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            conn.commit()

    def list_facts(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM facts ORDER BY key").fetchall()
        return {row["key"]: dict(row) for row in rows}

    # ── episodes (semantic) ────────────────────────────────

    def insert_episode(
        self,
        *,
        entry_id: str,
        text: str,
        source: str,
        tags: list[str] | None = None,
        created_at: str | None = None,
        embedding: bytes | None = None,
        embedding_backend: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO episodes
                (id, text, source, tags, created_at, embedding, embedding_backend)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    text,
                    source,
                    json.dumps(tags or []),
                    created_at or now,
                    embedding,
                    embedding_backend,
                ),
            )
            conn.commit()

    def delete_episode(self, entry_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM episodes WHERE id = ?", (entry_id,))
            conn.commit()
        return cur.rowcount > 0

    def get_episode(self, entry_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, text, source, tags, created_at FROM episodes WHERE id = ?",
                (entry_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        return d

    def list_episodes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY created_at ASC"
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d.get("tags") or "[]")
            d["embedding"] = unpack_embedding(d.get("embedding"))
            out.append(d)
        return out

    def episode_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM episodes").fetchone()
        return int(row["c"])

    def prune_oldest_episodes(self, keep: int) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM episodes ORDER BY created_at ASC"
            ).fetchall()
        excess = len(rows) - keep
        if excess <= 0:
            return 0
        for row in rows[:excess]:
            self.delete_episode(row["id"])
        return excess

    # ── messages (context) ─────────────────────────────────

    def append_message(self, message: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        tool_calls = message.get("tool_calls")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (role, content, tool_calls, tool_call_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message.get("role"),
                    message.get("content"),
                    json.dumps(tool_calls) if tool_calls else None,
                    message.get("tool_call_id"),
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)  # type: ignore[union-attr]

    def get_messages(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY id ASC"
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def get_messages_slice(self, start_id: int, end_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE id >= ? AND id <= ? ORDER BY id ASC",
                (start_id, end_id),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def delete_messages_up_to(self, max_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM messages WHERE id <= ?", (max_id,))
            conn.commit()
        return cur.rowcount

    def delete_empty_user_messages(self) -> int:
        """Remove blank user turns that break LM Studio / Qwen prompt templates."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM messages
                WHERE role = 'user'
                  AND (content IS NULL OR TRIM(content) = '')
                """
            )
            conn.commit()
            return int(cur.rowcount)

    def pop_last_message(self) -> bool:
        """Remove the most recent message (e.g. rollback a failed LLM turn)."""
        last_id = self.last_message_id()
        if last_id is None:
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE id = ?", (last_id,))
            conn.commit()
        return True

    def repair_message_history(self) -> dict[str, int]:
        """
        Fix SQLite context rows that break Qwen/LM Studio jinja templates.
        - Drop orphan user at end (crashed turn before assistant reply)
        - Drop dangling tool / tool-call assistant at end
        """
        stats = {"empty_users": 0, "orphan_users": 0, "dangling_tail": 0}
        stats["empty_users"] = self.delete_empty_user_messages()

        while True:
            msgs = self.get_messages()
            if not msgs or msgs[-1].get("role") != "user":
                break
            self.pop_last_message()
            stats["orphan_users"] += 1

        while True:
            msgs = self.get_messages()
            if not msgs:
                break
            last = msgs[-1]
            role = last.get("role")
            if role == "tool":
                self.pop_last_message()
                stats["dangling_tail"] += 1
                continue
            if role == "assistant" and last.get("tool_calls"):
                self.pop_last_message()
                stats["dangling_tail"] += 1
                continue
            break

        return stats

    def message_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()
        return int(row["c"])

    def first_message_id(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MIN(id) AS m FROM messages").fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    def last_message_id(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(id) AS m FROM messages").fetchone()
        return int(row["m"]) if row and row["m"] is not None else None

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "role": row["role"],
            "content": row["content"],
            "_id": row["id"],
        }
        if row["tool_calls"]:
            msg["tool_calls"] = json.loads(row["tool_calls"])
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        return msg

    def pop_oldest_messages(self, count: int) -> list[dict[str, Any]]:
        """Remove and return the oldest `count` messages."""
        if count <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM messages ORDER BY id ASC LIMIT ?", (count,)
            ).fetchall()
        if not rows:
            return []
        start_id, end_id = rows[0]["id"], rows[-1]["id"]
        removed = self.get_messages_slice(start_id, end_id)
        self.delete_messages_up_to(end_id)
        return removed

    # ── session ────────────────────────────────────────────

    def set_session(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
            conn.commit()

    def get_session(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM session_kv WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        return json.loads(row["value"])

    def all_session(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM session_kv").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def clear_session_keys(self, *keys: str) -> None:
        if not keys:
            return
        placeholders = ",".join("?" * len(keys))
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM session_kv WHERE key IN ({placeholders})", keys
            )
            conn.commit()
