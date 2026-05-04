import discord, time
from discord import app_commands
from discord.ext import commands
from config import *


class Utility(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot

  @app_commands.command(name="ping", description="Check bot latency")
  async def ping(self, interaction: discord.Interaction):
    latency = round(self.bot.latency * 1000)
    await interaction.response.send_message(f"Pong! {latency}ms")
    print(f"Pinged at {time.ctime()}")

async def setup(bot: commands.Bot):
  await bot.add_cog(Utility(bot))
