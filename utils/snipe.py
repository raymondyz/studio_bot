"""Database access layer and scoring for the snipe bot.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

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


# ---------- scoring ----------
# Scores are calculated from the snipe log rather than stored, so changing
# these constants rescores all past snipes too

# Snipe statuses that count towards scores
SCORED_STATUSES = ("pending", "confirmed")

# Bounty of a player who was just sniped
BASE_BOUNTY = 3

# Added to a player's bounty for every full week since they were last sniped
BOUNTY_PER_WEEK = 1

# Bounty of a player who has never been sniped
NEVER_SNIPED_BOUNTY = 6

# Extra points for each person sniped in a snipe
SNIPE_BONUS = 0

# Multiplies the points for each person sniped
GAME_MULTIPLIER = 1

# Points a player loses each time they're sniped
SNIPED_PENALTY = 2


def calculate_bounty(last_sniped_at: datetime | None, at: datetime) -> int:
  """A player's bounty at a given time. last_sniped_at is None if they've never been sniped."""
  if last_sniped_at is None:
    return NEVER_SNIPED_BOUNTY
  weeks = (at - last_sniped_at) // timedelta(weeks=1)
  return BASE_BOUNTY + BOUNTY_PER_WEEK * weeks


def calculate_player_bounty(snipes: Iterable[Snipe], player_id: int, at: datetime) -> int:
  """A player's bounty at a given time (usually now). Snipes after that time are ignored."""
  last_sniped_at = max(
    (
      snipe.sniped_at for snipe in snipes
      if snipe.status in SCORED_STATUSES
      and player_id in snipe.target_ids
      and snipe.sniped_at <= at
    ),
    default=None,
  )
  return calculate_bounty(last_sniped_at, at)


def _replay(snipes: Iterable[Snipe]) -> Iterator[tuple[Snipe, int, int]]:
  """Replays the snipe history in order, yielding (snipe, target_id, points)
  for each person sniped in each scored snipe.

  points is what sniping that person was worth to the sniper, from their bounty
  at the time.
  """
  last_sniped_at: dict[int, datetime] = {}

  for snipe in sorted(snipes, key=lambda snipe: (snipe.sniped_at, snipe.id)):
    if snipe.status not in SCORED_STATUSES:
      continue
    for target_id in snipe.target_ids:
      bounty = calculate_bounty(last_sniped_at.get(target_id), snipe.sniped_at)
      yield snipe, target_id, (bounty + SNIPE_BONUS) * GAME_MULTIPLIER
      last_sniped_at[target_id] = snipe.sniped_at


def calculate_scores(snipes: Iterable[Snipe]) -> dict[int, int]:
  """Replays the snipe history in order and returns {player_id: score}.

  Players who haven't been in a scored snipe are left out, so look scores up
  with .get(player_id, 0).
  """
  scores: dict[int, int] = defaultdict(int)
  for snipe, target_id, points in _replay(snipes):
    scores[snipe.sniper_id] += points
    scores[target_id] -= SNIPED_PENALTY
  return dict(scores)


def calculate_snipe_points(snipes: Iterable[Snipe], snipe_id: int) -> dict[int, int]:
  """What each person sniped in one snipe was worth to the sniper, as {target_id: points}.

  Empty if that snipe isn't in the history or doesn't count towards scores.
  """
  return {
    target_id: points
    for snipe, target_id, points in _replay(snipes)
    if snipe.id == snipe_id
  }


@dataclass(frozen=True)
class PlayerStats:
  points: int
  snipes: int  # snipes they made; a group snipe counts once
  times_sniped: int
  bounty: int


def calculate_player_stats(snipes: Iterable[Snipe], player_id: int, at: datetime) -> PlayerStats:
  """A player's stats at a given time (usually now). Snipes after that time are ignored."""
  scored = [
    snipe for snipe in snipes
    if snipe.status in SCORED_STATUSES and snipe.sniped_at <= at
  ]
  return PlayerStats(
    points=calculate_scores(scored).get(player_id, 0),
    snipes=sum(1 for snipe in scored if snipe.sniper_id == player_id),
    times_sniped=sum(1 for snipe in scored if player_id in snipe.target_ids),
    bounty=calculate_player_bounty(scored, player_id, at),
  )


@dataclass(frozen=True)
class LeaderboardEntry:
  rank: int
  player: Player
  points: int


def calculate_leaderboard(snipes: Iterable[Snipe], players: Iterable[Player]) -> list[LeaderboardEntry]:
  """Ranks players by points, highest first. Tied players share a rank (1, 2, 2, 4)."""
  scores = calculate_scores(snipes)
  ranked = sorted(players, key=lambda player: (-scores.get(player.id, 0), player.name.lower()))

  leaderboard: list[LeaderboardEntry] = []
  for position, player in enumerate(ranked, start=1):
    points = scores.get(player.id, 0)
    tied = len(leaderboard) > 0 and leaderboard[-1].points == points
    rank = leaderboard[-1].rank if tied else position
    leaderboard.append(LeaderboardEntry(rank, player, points))
  return leaderboard