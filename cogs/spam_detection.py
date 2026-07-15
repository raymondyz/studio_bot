import discord
from discord import app_commands
from discord.ext import commands
from config import *
from utils.discord import get_member_messages
from datetime import timedelta


class SpamDetection(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot

  async def _is_message_spam(self, member, message) -> bool:
    """Checks if a message fits the criteria for being a spam message

    Criteria: the number of identical messages sent to different channels by the same user reaches the set threshold within 2 mins
    """

    # Short messages don't count
    if len(message.content) < 20:
      return False

    spam_count = 0
    # Find identical messages in other channels
    for channel_id in SPAM_CHECK_CHANNELS:
      channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
      messages = await get_member_messages(channel, member, 5)
      
      for msg in messages:
        # Has to have same content and be sent within 2 minutes to count as a match
        if msg.content == message.content and abs(msg.created_at - message.created_at) <= timedelta(minutes=2):
          spam_count += 1
          break

    # Enough matches -> spam detected
    return spam_count >= SPAM_THRESHOLD
  
  async def _log_spam(self, user, message):
    """Log the detected spam in the logging channel"""

    print(f"Spam detected: {user.name} detected for the following spam: {message.content}")

    log_channel = self.bot.get_channel(LOGGING_CHANNEL) or await self.bot.fetch_channel(LOGGING_CHANNEL)

    return await log_channel.send(f"# **Spam Detected!**\n{user.mention} ({user.name}) has been detected for the following spam:\n```{message.content}```")
  
  async def _notify_spammer(self, user, message):
    """Direct message the spammer about the ban"""

    return await user.send(
      "# **You have been __banned__**!\n" \
      "You have been banned from the ACM Studio Discord for spamming. " \
      "The spam detection system is not perfect, so if you believe you have been wrongfully banned, " \
      f"please contact **{DEVELOPER_CONTACT}** or any other ACM Studio officer and they will happily assist you!\n\n"
      "Below is the message that caused your ban:\n" \
      f"```{message.content}```"
    )

  async def _purge_spam_messages(self, user, message):
    """Remove the spam message across all server channels"""

    def is_spam(msg):
      return (
        msg.author == user
        and msg.content == message.content
        and abs(msg.created_at - message.created_at) < timedelta(minutes=5)
      )

    for channel in message.guild.text_channels + message.guild.voice_channels:
      perms = channel.permissions_for(channel.guild.me)
      if not (perms.read_message_history and perms.manage_messages):
        continue
      try:
        # Remove all messages that match the is_spam criteria
        await channel.purge(limit=5, check=is_spam)
      except (discord.Forbidden, discord.HTTPException):
        continue
    

  @commands.Cog.listener()
  async def on_message(self, message):
    # Ignore messages from itself
    if message.author == self.bot.user:
      return
    
    # Only check messages in spam channels
    if message.channel.id not in SPAM_CHECK_CHANNELS:
      return
    
    if await self._is_message_spam(message.author, message):
      user = self.bot.get_user(message.author.id) or await self.bot.fetch_user(message.author.id)
      # Log the detection and notify the spammer about their ban
      log_message = await self._log_spam(user, message)
      notify_message = await self._notify_spammer(user, message) # This must be done before the ban, so DMs go though
      try:
        # Attempt to ban spammer and purge messages
        await message.author.ban(reason="Studio Bot auto-ban: spamming")
        await self._purge_spam_messages(user, message)
      except Exception as e:
        await log_message.reply(f"Ban and purge failed: `{e}`")
        await notify_message.delete()
        raise
      else:
        await log_message.reply("Successfully banned spammer and purged messages!")
        print("Successfully banned and purged!")


async def setup(bot: commands.Bot):
  await bot.add_cog(SpamDetection(bot))