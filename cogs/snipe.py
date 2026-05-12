import discord, time
from discord import app_commands
from discord.ext import commands
from config import *

from utils.sheet_utils import get_spreadsheet, get_worksheet, add_row


snipe_spread = get_spreadsheet(SNIPE_SPREAD_LINK)
snipe_sheet = get_worksheet(snipe_spread, SNIPE_LOG_SHEET_NAME)

async def record_snipe(
  sniper_id: int,
  sniper_name: str,
  target_id: int,
  target_name: str,
  message_url: str = None
) -> None:
  await add_row(
    snipe_sheet,
    [
      sniper_id,
      sniper_name,
      target_id,
      target_name,
      time.ctime(),
      message_url
    ]
  )


class Snipe(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot


  @app_commands.command(name="snipe", description='Snipe an officer or intern!')
  @app_commands.describe(target = 'Your target...')
  @app_commands.describe(proof = "Proof you caught them lacking!")
  @app_commands.describe(message = "What do you have to say to person you sniped in cold blood...")
  async def submit_run(
    self,
    interaction: discord.Interaction,
    target: discord.Member,
    proof: discord.Attachment,
    message: str,
  ):
    
    # Check if user can snipe
    if not any(role.id in SNIPEABLE_ROLES for role in interaction.user.roles):
      await interaction.response.send_message(
        "You do not have permission to use this command.",
        ephemeral=True
      )
      return
    
    # Check if channel allowed
    if (interaction.channel_id not in SNIPEABLE_CHANNELS):
      await interaction.response.send_message(
        "You can only snipe people in the designated channel!",
        ephemeral=True
      )
      return

    # Check if attachment is an image
    ALLOWED_MIME = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    ct = (proof.content_type or "").lower()
    if ct not in ALLOWED_MIME:
      await interaction.response.send_message(
        "Please upload an **image file** (png, jpg, jpeg, gif, webp).",
        ephemeral=True
      )
      return
    
    # Check if target can be sniped
    if not any(role.id in SNIPEABLE_ROLES for role in target.roles):
      await interaction.response.send_message(
        "Only officers and interns can be sniped!",
        ephemeral=True
      )
      return
    
    
    # Send message
    embed_message = message
    embed = discord.Embed(
      title=embed_message,
      color=0xff0000,
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    embed.set_image(url=proof.url)

    await interaction.response.send_message(
      content = f"## 💥 BANG! {interaction.user.display_name} caught {target.mention} lacking in 4K!",
      embed=embed,
    )
    bot_response = await interaction.original_response()
  
    # Record snipe
    await record_snipe(
      sniper_id=interaction.user.id,
      sniper_name=interaction.user.display_name,
      target_id=target.id,
      target_name=target.display_name,
      message_url=bot_response.jump_url,
    )

    # Log
    print(f"{interaction.user.display_name} sniped {target.display_name} at {time.ctime()}")


async def setup(bot: commands.Bot):
  await bot.add_cog(Snipe(bot))
