"""Database access layer for the snipe bot.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite

SNIPE_STATUSES = ("pending", "confirmed", "voided")


@dataclass(frozen=True)
class Player:
  id: int
  discord_id: int
  name: str
  active: bool
  joined_at: datetime


@dataclass(frozen=True)
class Snipe:
  id: int
  message_id: int
  sniper_id: int
  sniped_at: datetime
  status: str
  target_ids: tuple[int, ...]


# ---------- conversion helpers ----------

def _to_db_time(dt: datetime) -> str:
  if dt.tzinfo is None:
    raise ValueError("datetimes must be timezone-aware")
  return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_db_time(value: str) -> datetime:
  # joined_at's SQL default ends in "Z", which fromisoformat only accepts on 3.11+
  return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _row_to_player(row: aiosqlite.Row) -> Player:
  return Player(
    id=row["id"],
    discord_id=row["discord_id"],
    name=row["name"],
    active=bool(row["active"]),
    joined_at=_from_db_time(row["joined_at"]),
  )


def _row_to_snipe(row: aiosqlite.Row) -> Snipe:
  raw = row["target_ids"]
  targets = tuple(sorted(int(t) for t in raw.split(","))) if raw else ()
  return Snipe(
    id=row["id"],
    message_id=row["message_id"],
    sniper_id=row["sniper_id"],
    sniped_at=_from_db_time(row["sniped_at"]),
    status=row["status"],
    target_ids=targets,
  )


def _placeholders(n: int) -> str:
  return ", ".join("?" * n)


def _clean_targets(sniper_id: int, target_ids: Iterable[int]) -> list[int]:
  targets = list(dict.fromkeys(target_ids))  # dedupe, keep order
  if not targets:
    raise ValueError("a snipe needs at least one target")
  if sniper_id in targets:
    raise ValueError("a player cannot snipe themselves")
  return targets


# One query that returns each snipe with its targets packed as "3,7,12".
# Only ever combined with fixed WHERE clauses below, never with user input.
_SNIPE_SELECT = """
  SELECT s.id, s.message_id, s.sniper_id, s.sniped_at, s.status,
         GROUP_CONCAT(t.target_id) AS target_ids
  FROM snipes s
  LEFT JOIN snipe_targets t ON t.snipe_id = s.id
"""


class SnipesDatabase:
  def __init__(self, conn: aiosqlite.Connection):
    self._conn = conn
    # All coroutines share one connection, so without this lock one
    # coroutine's commit could accidentally commit another's half-done writes
    self._write_lock = asyncio.Lock()

  # ---------- lifecycle ----------

  @classmethod
  async def connect(cls, db_path: Path, schema_path: Path) -> SnipesDatabase:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.executescript(schema_path.read_text())
    await conn.commit()
    return cls(conn)

  async def close(self) -> None:
    await self._conn.close()

  @asynccontextmanager
  async def _transaction(self):
    async with self._write_lock:
      try:
        yield self._conn
        await self._conn.commit()
      except Exception:
        await self._conn.rollback()
        raise

  # ---------- players ----------

  async def add_player(self, discord_id: int, name: str) -> Player | None:
    """Register a player. Returns None if this Discord user is already registered."""
    try:
      async with self._transaction() as conn:
        cursor = await conn.execute(
          "INSERT INTO players (discord_id, name) VALUES (?, ?)",
          (discord_id, name),
        )
        player_id = cursor.lastrowid
    except aiosqlite.IntegrityError:
      return None
    return await self.get_player(player_id)

  async def get_player(self, player_id: int) -> Player | None:
    async with self._conn.execute(
      "SELECT * FROM players WHERE id = ?", (player_id,)
    ) as cursor:
      row = await cursor.fetchone()
    return _row_to_player(row) if row else None

  async def get_player_by_discord_id(self, discord_id: int) -> Player | None:
    async with self._conn.execute(
      "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
    ) as cursor:
      row = await cursor.fetchone()
    return _row_to_player(row) if row else None

  async def get_players_by_discord_ids(
    self, discord_ids: Iterable[int]
  ) -> dict[int, Player]:
    """Resolve many Discord IDs at once, e.g. every mention in a message.

    Returns {discord_id: Player}; unregistered IDs are simply absent.
    """
    ids = list(set(discord_ids))
    if not ids:
      return {}
    rows = await self._conn.execute_fetchall(
      f"SELECT * FROM players WHERE discord_id IN ({_placeholders(len(ids))})",
      ids,
    )
    return {row["discord_id"]: _row_to_player(row) for row in rows}

  async def list_players(self, active_only: bool = True) -> list[Player]:
    sql = "SELECT * FROM players"
    if active_only:
      sql += " WHERE active = 1"
    rows = await self._conn.execute_fetchall(sql + " ORDER BY name")
    return [_row_to_player(row) for row in rows]

  async def set_player_active(self, player_id: int, active: bool) -> bool:
    """Returns False if no such player."""
    async with self._transaction() as conn:
      cursor = await conn.execute(
        "UPDATE players SET active = ? WHERE id = ?", (int(active), player_id)
      )
    return cursor.rowcount > 0

  async def rename_player(self, player_id: int, name: str) -> bool:
    """Returns False if no such player."""
    async with self._transaction() as conn:
      cursor = await conn.execute(
        "UPDATE players SET name = ? WHERE id = ?", (name, player_id)
      )
    return cursor.rowcount > 0

  # ---------- snipes ----------

  async def record_snipe(
    self,
    message_id: int,
    sniper_id: int,
    sniped_at: datetime,
    target_ids: Iterable[int],
  ) -> Snipe | None:
    """Record a new pending snipe.

    Returns None if this message was already recorded, which makes
    reprocessing channel history after downtime safe. Raises ValueError
    for invalid targets, and IntegrityError if a player ID doesn't exist.
    """
    targets = _clean_targets(sniper_id, target_ids)
    async with self._transaction() as conn:
      cursor = await conn.execute(
        """
        INSERT INTO snipes (message_id, sniper_id, sniped_at)
        VALUES (?, ?, ?)
        ON CONFLICT (message_id) DO NOTHING
        """,
        (message_id, sniper_id, _to_db_time(sniped_at)),
      )
      if cursor.rowcount == 0:
        return None
      snipe_id = cursor.lastrowid
      await conn.executemany(
        "INSERT INTO snipe_targets (snipe_id, target_id) VALUES (?, ?)",
        [(snipe_id, target_id) for target_id in targets],
      )
    return await self.get_snipe(snipe_id)

  async def _fetch_snipes(self, where: str = "", params: tuple = ()) -> list[Snipe]:
    sql = f"{_SNIPE_SELECT} {where} GROUP BY s.id ORDER BY s.sniped_at, s.id"
    rows = await self._conn.execute_fetchall(sql, params)
    return [_row_to_snipe(row) for row in rows]

  async def get_snipe(self, snipe_id: int) -> Snipe | None:
    snipes = await self._fetch_snipes("WHERE s.id = ?", (snipe_id,))
    return snipes[0] if snipes else None

  async def get_snipe_by_message_id(self, message_id: int) -> Snipe | None:
    snipes = await self._fetch_snipes("WHERE s.message_id = ?", (message_id,))
    return snipes[0] if snipes else None

  async def list_snipes(self, include_voided: bool = False) -> list[Snipe]:
    """Every snipe in chronological order: the input to your scoring function."""
    if include_voided:
      return await self._fetch_snipes()
    return await self._fetch_snipes("WHERE s.status != 'voided'")

  async def list_pending_snipes(self, older_than: datetime) -> list[Snipe]:
    """Pending snipes made at or before older_than, for auto-confirmation."""
    return await self._fetch_snipes(
      "WHERE s.status = 'pending' AND s.sniped_at <= ?",
      (_to_db_time(older_than),),
    )

  async def set_snipe_status(self, snipe_id: int, status: str) -> bool:
    """Returns False if no such snipe."""
    if status not in SNIPE_STATUSES:
      raise ValueError(f"status must be one of {SNIPE_STATUSES}")
    async with self._transaction() as conn:
      cursor = await conn.execute(
        "UPDATE snipes SET status = ? WHERE id = ?", (status, snipe_id)
      )
    return cursor.rowcount > 0

  async def set_snipe_targets(self, snipe_id: int, target_ids: Iterable[int]) -> bool:
    """Replace a snipe's targets, e.g. after the message is edited.

    Returns False if no such snipe.
    """
    snipe = await self.get_snipe(snipe_id)
    if snipe is None:
      return False
    targets = _clean_targets(snipe.sniper_id, target_ids)
    async with self._transaction() as conn:
      await conn.execute("DELETE FROM snipe_targets WHERE snipe_id = ?", (snipe_id,))
      await conn.executemany(
        "INSERT INTO snipe_targets (snipe_id, target_id) VALUES (?, ?)",
        [(snipe_id, target_id) for target_id in targets],
      )
    return True

  async def latest_snipe_message_id(self) -> int | None:
    """Where to resume reading channel history on startup."""
    async with self._conn.execute("SELECT MAX(message_id) FROM snipes") as cursor:
      row = await cursor.fetchone()
    return row[0]