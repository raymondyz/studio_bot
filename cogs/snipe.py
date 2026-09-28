import re
import asyncio
import discord
from datetime import datetime, timedelta, timezone
from typing import Iterable
from discord import app_commands
from discord.ext import commands
from config import *

from utils.snipe import (
  Player,
  Snipe as SnipeRecord,
  calculate_bounties,
  calculate_leaderboard,
  calculate_player_stats,
  calculate_snipe_points,
)

# Matches <@id> and the legacy nickname form <@!id>, but not role mentions (<@&id>)
USER_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

# Formats accepted for custom snipe dates
DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d")

# How many messages after a snipe to search for the bot's reply to it
REPLY_SEARCH_LIMIT = 50


def _within_change_window(sent_at: datetime) -> bool:
  return datetime.now(timezone.utc) - sent_at <= timedelta(hours=SNIPE_CHANGE_WINDOW_HOURS)


def _is_changeable(snipe: SnipeRecord | None) -> bool:
  """Snipes can be voided or edited while they're pending, until the change window ends."""
  return snipe is not None and snipe.status == "pending" and _within_change_window(snipe.sniped_at)


def _voided_content(content: str, reason: str) -> str:
  """A snipe reply, crossed out with why it was voided."""
  return f"~~{content}~~\n**{reason}** (voided)"


class NotASnipeButton(discord.ui.DynamicItem[discord.ui.Button], template=r"snipe:void:(?P<snipe_id>\d+)"):
  """Lets the sniper or an admin void a snipe shortly after it's made.

  The snipe ID is stored in the button itself, so buttons keep working after the bot restarts.
  """

  def __init__(self, snipe_id: int):
    super().__init__(
      discord.ui.Button(
        label="Not a snipe",
        style=discord.ButtonStyle.secondary,
        custom_id=f"snipe:void:{snipe_id}",
      )
    )
    self.snipe_id = snipe_id

  @classmethod
  async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
    return cls(int(match["snipe_id"]))

  async def callback(self, interaction: discord.Interaction):
    db = interaction.client.snipes_db
    snipe = await db.get_snipe(self.snipe_id)

    # Check if it's too late. The button is normally removed on time, but not if the bot restarted
    if not _is_changeable(snipe):
      await interaction.response.edit_message(view=None)
      await interaction.followup.send("It's too late to undo this snipe.", ephemeral=True)
      return

    # Check if user is the sniper or an admin
    sniper = await db.get_player(snipe.sniper_id)
    if interaction.user.id != sniper.discord_id and interaction.user.id not in ADMIN_USERS:
      await interaction.response.send_message(
        "Only the sniper or an admin can undo this snipe.",
        ephemeral=True
      )
      return

    await db.set_snipe_status(snipe.id, "voided")
    await interaction.response.edit_message(
      content=_voided_content(interaction.message.content, "Not a snipe"),
      view=None,
      allowed_mentions=discord.AllowedMentions.none()
    )
    print(f"{interaction.user} voided snipe {snipe.id}")


class Snipe(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot
    # Timers that remove "Not a snipe" buttons, kept so they aren't garbage collected
    self._button_timers: set[asyncio.Task] = set()

  # ---------- helpers ----------

  @staticmethod
  def _extract_mentions(content: str) -> list[int]:
    user_ids = [int(user_id) for user_id in USER_MENTION_PATTERN.findall(content)]
    return list(dict.fromkeys(user_ids))  # dedupe, keep order

  @staticmethod
  def _is_snipeable(member: discord.Member | None) -> bool:
    return member is not None and any(role.id in SNIPEABLE_ROLES for role in member.roles)

  @staticmethod
  def _parse_date(text: str) -> datetime | None:
    # Dates are entered in the club's local time
    for date_format in DATE_FORMATS:
      try:
        return datetime.strptime(text.strip(), date_format).replace(tzinfo=SNIPE_TIMEZONE)
      except ValueError:
        pass
    return None

  @staticmethod
  def _display_name(player: Player) -> str:
    """The real name a player was added with, safe to put in markdown."""
    return discord.utils.escape_markdown(player.name)

  @staticmethod
  async def _check_admin(interaction: discord.Interaction) -> bool:
    """Returns whether the user is a bot admin, and tells them if they aren't."""
    if interaction.user.id in ADMIN_USERS:
      return True
    await interaction.response.send_message(
      "Only bot admins can use this command.",
      ephemeral=True
    )
    return False

  @staticmethod
  async def _check_snipe_channel(interaction: discord.Interaction) -> bool:
    """Returns whether the command was used in a snipe channel, and tells the user if it wasn't.

    Player commands only work in snipe channels, admin commands work anywhere.
    """
    if interaction.channel_id in SNIPEABLE_CHANNELS:
      return True
    await interaction.response.send_message(
      "You can only use snipe commands in the snipe channel!",
      ephemeral=True
    )
    return False

  # ---------- admin commands ----------

  player = app_commands.Group(name="player", description="Manage snipe players", guild_only=True)

  @player.command(name="add", description="Add someone to the snipe game")
  @app_commands.describe(member="Who to add")
  @app_commands.describe(name="Their real name, shown on the leaderboards and stats")
  async def player_add(self, interaction: discord.Interaction, member: discord.Member, name: str):
    if not await Snipe._check_admin(interaction):
      return

    db = self.bot.snipes_db
    player = await db.get_player_by_discord_id(member.id)

    if player is None:
      await db.add_player(member.id, name)
      response = f"Added {member.mention} ({name}) to the snipe game!"
    elif not player.active:
      # Previously removed players are reactivated, keeping their history
      await db.set_player_active(player.id, True)
      await db.rename_player(player.id, name)
      response = f"Welcome back {member.mention} ({name}), your snipe history was kept!"
    else:
      await interaction.response.send_message(
        f"{member.mention} is already a player.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
      )
      return

    if not Snipe._is_snipeable(member):
      response += "\nThey don't have a snipeable role yet, so they can't snipe or be sniped until they get one."

    await interaction.response.send_message(response, allowed_mentions=discord.AllowedMentions.none())
    print(f"{interaction.user} added {member} as a player")

  @player.command(name="remove", description="Remove someone from the snipe game (their history is kept)")
  @app_commands.describe(user="Who to remove")
  async def player_remove(self, interaction: discord.Interaction, user: discord.User):
    if not await Snipe._check_admin(interaction):
      return

    # Players are deactivated rather than deleted, so their history is kept
    db = self.bot.snipes_db
    player = await db.get_player_by_discord_id(user.id)
    if player is None or not player.active:
      await interaction.response.send_message(
        f"{user.mention} isn't a player.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
      )
      return

    await db.set_player_active(player.id, False)
    await interaction.response.send_message(
      f"Removed {user.mention} from the snipe game.",
      allowed_mentions=discord.AllowedMentions.none()
    )
    print(f"{interaction.user} removed {user} as a player")

  @app_commands.command(name="admin-snipe", description="Record a snipe on someone's behalf (admin only)")
  @app_commands.describe(sniper="Who took the photo")
  @app_commands.describe(targets="Ping everyone who was sniped")
  @app_commands.describe(date='When it happened, as "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" (leave blank for now)')
  @app_commands.guild_only()
  async def admin_snipe(
    self,
    interaction: discord.Interaction,
    sniper: discord.User,
    targets: str,
    date: str | None = None,
  ):
    if not await Snipe._check_admin(interaction):
      return

    # Use the given date, or now if left blank
    if date is None:
      sniped_at = datetime.now(timezone.utc)
    else:
      sniped_at = Snipe._parse_date(date)
      if sniped_at is None:
        await interaction.response.send_message(
          'Please enter the date as "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" (ex "2026-09-20 14:30").',
          ephemeral=True
        )
        return
      if sniped_at > datetime.now(timezone.utc):
        await interaction.response.send_message(
          "That date is in the future.",
          ephemeral=True
        )
        return

    # Check if there are targets
    target_discord_ids = [target for target in Snipe._extract_mentions(targets) if target != sniper.id]
    if len(target_discord_ids) == 0:
      await interaction.response.send_message(
        "Please ping at least one person who was sniped (other than the sniper).",
        ephemeral=True
      )
      return

    # Check if everyone is an active player. Unlike normal snipes, nobody is silently dropped
    db = self.bot.snipes_db
    everyone = [sniper.id, *target_discord_ids]
    players = await db.get_players_by_discord_ids(everyone)
    not_players = [
      discord_id for discord_id in everyone
      if discord_id not in players or not players[discord_id].active
    ]
    if len(not_players) > 0:
      await interaction.response.send_message(
        f"These people aren't players: {' '.join(f'<@{discord_id}>' for discord_id in not_players)}",
        ephemeral=True
      )
      return

    # Mentions show names without pinging, so backfilling old snipes doesn't spam anyone
    target_mentions = " ".join(f"<@{discord_id}>" for discord_id in target_discord_ids)
    await interaction.response.send_message(
      f"Recorded snipe: {sniper.mention} sniped {target_mentions} on <t:{int(sniped_at.timestamp())}:f>",
      allowed_mentions=discord.AllowedMentions.none()
    )

    # The confirmation message stands in for the ping message a normal snipe is recorded from
    response = await interaction.original_response()
    await db.record_snipe(
      response.id,
      players[sniper.id].id,
      sniped_at,
      [players[discord_id].id for discord_id in target_discord_ids]
    )
    print(f"{interaction.user} recorded a snipe by {sniper}")

  # ---------- player commands ----------
  # Snipe commands are named snipe-<name>

  @app_commands.command(name="snipe-stats", description="See a player's snipe stats")
  @app_commands.describe(player="Whose stats to see (leave blank for your own)")
  @app_commands.guild_only()
  async def snipe_stats(self, interaction: discord.Interaction, player: discord.User | None = None):
    if not await Snipe._check_snipe_channel(interaction):
      return

    if player is None:
      player = interaction.user

    # Check if they're a player
    db = self.bot.snipes_db
    db_player = await db.get_player_by_discord_id(player.id)
    if db_player is None:
      await interaction.response.send_message(
        f"{player.mention} isn't a player.",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
      )
      return

    stats = calculate_player_stats(await db.list_snipes(), db_player.id, datetime.now(timezone.utc))

    embed = discord.Embed(
      title=f"{db_player.name}'s snipe stats",
      color=0xff0000,
    )
    if not db_player.active:
      embed.description = "No longer playing"
    embed.set_thumbnail(url=player.display_avatar.url)
    embed.add_field(name="Points", value=stats.points)
    embed.add_field(name="Bounty", value=stats.bounty)
    embed.add_field(name="​", value="​")  # blank field, so the next row lines up
    embed.add_field(name="Snipes", value=stats.snipes)
    embed.add_field(name="Times sniped", value=stats.times_sniped)
    embed.add_field(name="​", value="​")

    await interaction.response.send_message(embed=embed)

  @app_commands.command(name="snipe-leaderboard", description="See every player ranked by points")
  @app_commands.guild_only()
  async def snipe_leaderboard(self, interaction: discord.Interaction):
    if not await Snipe._check_snipe_channel(interaction):
      return

    db = self.bot.snipes_db
    leaderboard = calculate_leaderboard(await db.list_snipes(), await db.list_players())

    # Check if there are players
    if len(leaderboard) == 0:
      await interaction.response.send_message("There are no players yet!")
      return

    lines = [
      f"**{entry.rank}.** {Snipe._display_name(entry.player)}: {entry.points} pts"
      for entry in leaderboard
    ]
    embed = discord.Embed(
      title="Snipe Leaderboard",
      description="\n".join(lines),
      color=0xff0000,
    )
    await interaction.response.send_message(embed=embed)

  @app_commands.command(name="snipe-bounties", description="See every player's bounty, highest first")
  @app_commands.guild_only()
  async def snipe_bounties(self, interaction: discord.Interaction):
    if not await Snipe._check_snipe_channel(interaction):
      return

    db = self.bot.snipes_db
    bounties = calculate_bounties(await db.list_snipes(), await db.list_players(), datetime.now(timezone.utc))

    # Check if there are players
    if len(bounties) == 0:
      await interaction.response.send_message("There are no players yet!")
      return

    lines = [
      f"{Snipe._display_name(player)}: {bounty} pts"
      for player, bounty in bounties
    ]
    embed = discord.Embed(
      title="Snipe Bounties",
      description="\n".join(lines),
      color=0xff0000,
    )
    await interaction.response.send_message(embed=embed)

  # ---------- snipe messages ----------
  # Raw events are used for edits and deletes because the normal ones skip messages
  # sent before the bot last started

  @commands.Cog.listener()
  async def on_message(self, message: discord.Message):
    found = await self._read_snipe(message)
    if found is not None:
      await self._record_snipe(message, *found)

  @commands.Cog.listener()
  async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
    message = payload.message

    # Ignore the bot's own messages, which include its replies and admin snipe records
    if message.author.bot or message.channel.id not in SNIPEABLE_CHANNELS:
      return

    # Messages can only change snipes within the change window
    if not _within_change_window(message.created_at):
      return

    db = self.bot.snipes_db
    snipe = await db.get_snipe_by_message_id(message.id)
    found = await self._read_snipe(message)

    # A message edited to add pings becomes a new snipe
    if snipe is None:
      if found is not None:
        await self._record_snipe(message, *found)
      return

    if not _is_changeable(snipe):
      return

    # A snipe edited to remove every ping is voided
    if found is None:
      await self._void_snipe(snipe, message.channel, "Pings removed")
      return

    # Otherwise update who was sniped. Edits that don't change the pings, like Discord
    # adding a link preview, are ignored
    sniper, sniped = found
    target_ids = tuple(sorted(player.id for player in sniped))
    if target_ids == snipe.target_ids:
      return
    await db.set_snipe_targets(snipe.id, target_ids)
    reply = await self._find_reply(message.channel, message.id)
    if reply is not None:
      await reply.edit(
        content=await self._describe_snipe(snipe.id, sniper, sniped),
        allowed_mentions=discord.AllowedMentions.none()
      )
    print(f"{message.author} changed who they sniped in snipe {snipe.id}")

  @commands.Cog.listener()
  async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
    await self._void_deleted(payload.channel_id, [payload.message_id])

  @commands.Cog.listener()
  async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
    await self._void_deleted(payload.channel_id, payload.message_ids)

  async def _read_snipe(self, message: discord.Message) -> tuple[Player, list[Player]] | None:
    """Who a message says sniped whom, as (sniper, sniped), or None if it isn't a snipe."""
    # Ignore bots, including itself, and webhooks (their authors aren't members, so have no roles)
    if message.author.bot:
      return None

    # Ignore messages not in snipe channels
    if message.channel.id not in SNIPEABLE_CHANNELS:
      return None

    # Ignore messages by users without snipeable roles. Edited messages don't always
    # come with the author's roles, so fall back to the server's member list
    author = message.author
    if not isinstance(author, discord.Member):
      author = message.guild.get_member(author.id)
    if not Snipe._is_snipeable(author):
      return None

    # Keep targets still in the server with a snipeable role
    targets = [
      target for target in Snipe._extract_mentions(message.content)
      if target != message.author.id and Snipe._is_snipeable(message.guild.get_member(target))
    ]
    if len(targets) == 0:
      return None

    # The database identifies players by its own IDs. Removed players are kept but inactive
    db = self.bot.snipes_db
    sniper = await db.get_player_by_discord_id(message.author.id)
    if sniper is None or not sniper.active:
      return None
    players = await db.get_players_by_discord_ids(targets)
    sniped = [
      players[target] for target in targets
      if target in players and players[target].active
    ]
    if len(sniped) == 0:
      return None

    return sniper, sniped

  async def _describe_snipe(self, snipe_id: int, sniper: Player, sniped: list[Player]) -> str:
    """The reply to a snipe: who sniped whom, and what it was worth."""
    points = calculate_snipe_points(await self.bot.snipes_db.list_snipes(), snipe_id)
    if len(sniped) == 1:
      return f"💥 <@{sniper.discord_id}> sniped <@{sniped[0].discord_id}> for **{points.get(sniped[0].id, 0)}** points!"
    parts = [f"<@{player.discord_id}> (+{points.get(player.id, 0)})" for player in sniped]
    return f"💥 <@{sniper.discord_id}> sniped {', '.join(parts[:-1])} and {parts[-1]} for **{sum(points.values())}** points!"

  async def _record_snipe(self, message: discord.Message, sniper: Player, sniped: list[Player]):
    """Records a snipe from a message, then replies with what it was worth and a "Not a snipe" button."""
    db = self.bot.snipes_db
    snipe = await db.record_snipe(message.id, sniper.id, message.created_at, [player.id for player in sniped])
    if snipe is None:
      return  # this message was already recorded
    print(f"{message.author} sniped someone!")

    view = discord.ui.View(timeout=None)
    view.add_item(NotASnipeButton(snipe.id))
    reply = await message.reply(
      await self._describe_snipe(snipe.id, sniper, sniped),
      view=view,
      allowed_mentions=discord.AllowedMentions.none()
    )

    # Remove the button once the change window ends
    expires_at = snipe.sniped_at + timedelta(hours=SNIPE_CHANGE_WINDOW_HOURS)
    timer = asyncio.create_task(Snipe._remove_button_at(reply, expires_at))
    self._button_timers.add(timer)
    timer.add_done_callback(self._button_timers.discard)

  async def _find_reply(self, channel: discord.abc.Messageable, message_id: int) -> discord.Message | None:
    """The bot's reply to a snipe message. It isn't stored, but it's always soon after the message."""
    after = discord.Object(id=message_id)
    async for message in channel.history(after=after, limit=REPLY_SEARCH_LIMIT, oldest_first=True):
      if (
        message.author.id == self.bot.user.id
        and message.reference is not None
        and message.reference.message_id == message_id
      ):
        return message
    return None

  async def _void_snipe(self, snipe: SnipeRecord, channel: discord.abc.Messageable, reason: str):
    """Voids a snipe and crosses out the bot's reply to it."""
    await self.bot.snipes_db.set_snipe_status(snipe.id, "voided")
    reply = await self._find_reply(channel, snipe.message_id)
    if reply is not None:
      await reply.edit(
        content=_voided_content(reply.content, reason),
        view=None,
        allowed_mentions=discord.AllowedMentions.none()
      )
    print(f"Voided snipe {snipe.id}: {reason}")

  async def _void_deleted(self, channel_id: int, message_ids: Iterable[int]):
    """Voids the snipes of deleted messages, if they can still be changed."""
    if channel_id not in SNIPEABLE_CHANNELS:
      return
    db = self.bot.snipes_db
    channel = self.bot.get_partial_messageable(channel_id)
    for message_id in message_ids:
      snipe = await db.get_snipe_by_message_id(message_id)
      if _is_changeable(snipe):
        await self._void_snipe(snipe, channel, "Message deleted")

  @staticmethod
  async def _remove_button_at(message: discord.Message, when: datetime):
    await asyncio.sleep((when - datetime.now(timezone.utc)).total_seconds())
    try:
      await message.edit(view=None)
    except discord.HTTPException:
      pass  # the reply was deleted


async def setup(bot: commands.Bot):
  # Lets "Not a snipe" buttons sent before a restart keep working
  bot.add_dynamic_items(NotASnipeButton)
  await bot.add_cog(Snipe(bot))
