import discord
from discord import app_commands
from discord.ext import commands
from config import *


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

    
    # Record snipe
    
    # Send message
    embed_message = f"{message}!"
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


async def setup(bot: commands.Bot):
  await bot.add_cog(Snipe(bot))
