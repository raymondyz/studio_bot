from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
import asyncio
import os
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
