from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import traceback
import sys

from config import *

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
  print(f"Logged in as {bot.user}")
  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s)")
  except Exception as e:
    print(f"Sync failed: {e}")

# Bot wide slash command error handler
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
  traceback.print_exception(type(error), error, error.__traceback__)
  msg = f"Something went wrong: {error}"
  if interaction.response.is_done():
    await interaction.followup.send(msg, ephemeral=True)
  else:
    await interaction.response.send_message(msg, ephemeral=True)

# Bot wide prefix command error handler
@bot.event
async def on_command_error(ctx, error):
  if isinstance(error, commands.CommandNotFound):
    return  # ignore unknown commands
  traceback.print_exception(type(error), error, error.__traceback__)
  await ctx.send(f"Error: {error}")

# Bot wide on_event error handler
@bot.event
async def on_error(event_method, *args, **kwargs):
  print(f"Exception in {event_method}:", file=sys.stderr)
  traceback.print_exc()


async def load_cogs():
  for filename in os.listdir("./cogs"):
    if filename.endswith(".py"):
      await bot.load_extension(f"cogs.{filename[:-3]}")
      print(f"Loaded {filename}")

async def main():
  async with bot:
    await load_cogs()
    await bot.start(TOKEN)

asyncio.run(main())
