import discord, json, os, time
from dotenv import load_dotenv
from config import *
from discord import app_commands
from discord.ext import commands
from utils.llm_utils import query_llm

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print("Bot is Ready!")

@bot.event
async def setup_hook():
  # Sync slash commands when the bot starts
  await bot.tree.sync()
  print("Synced slash commands.")




@bot.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
  await interaction.response.send_message("Pong!")
  print(f"Pinged at {time.ctime()}")

@bot.tree.command(name="leaderboard", description='View the top 10 runs for the game "Getting Over It"!')
async def leaderboard(
  interaction: discord.Interaction
):
  runs = load_and_sort_runs()

  # Check if there are runs
  if runs == None or len(runs) == 0:
    await interaction.response.send_message(
      "There are no runs submitted yet, maybe you can be the first!"
    )
    return
  
  # Construct leaderboard
  response = "**Getting Over It Leaderboard:**\n"
  for i in range(min(10, len(runs))):
    run = runs[i]

    user = await bot.fetch_user(run["user_id"])
    formatted_time = format_time(run["time"])
    response += f"{formatted_time} - {user.display_name}\n"
  
  await interaction.response.send_message(
    response
  )

@bot.tree.command(name="submit-run", description='Submit a run for the game "Getting Over It"!')
@app_commands.describe(completion_time = 'Your completion time in hh:mm:ss (ex "00:42:03" for 42min 3sec)')
@app_commands.describe(proof = "A screenshot of you making it to the end as proof!")
async def submit_run(
  interaction: discord.Interaction,
  completion_time: str,
  proof: discord.Attachment
):
  
  # Check if channel allowed
  if (interaction.channel_id not in SPEEDRUN_SUBMIT_CHANNELS):
    await interaction.response.send_message(
      "You can only submit runs in the designated channel!",
      ephemeral=True
    )
    return
  
  # Check if attachment is an image

  # 1. Prefer checking MIME type if Discord provides it
  ct = proof.content_type  # e.g. "image/png", "image/jpeg", etc.
  is_image = False
  if ct is not None:
    is_image = ct.startswith("image/")
  else:
    # 2. Fallback: check extension
    filename = proof.filename.lower()
    allowed_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    is_image = filename.endswith(allowed_exts)

  if not is_image:
    await interaction.response.send_message(
      "Please upload an **image file** (png, jpg, jpeg, gif, webp).",
      ephemeral=True
    )
    return
  
  # Check if time is valid
  time_secs = parse_time(completion_time)
  if time_secs == None:
    await interaction.response.send_message(
      'Please submit your time in hh:mm:ss format (ex "00:42:03" for 42min 3sec).',
      ephemeral=True
    )
    return
  
  # Run submitted

  # Record run to file
  record_run(interaction.user.id, time_secs)
  print(f"A new run was submitted at {time.ctime()}")
  
  # Send message
  embed_message = f"{interaction.user.display_name} completed the game in {format_time(time_secs)}!"
  embed = discord.Embed(
    title=embed_message,
    color=0xff0000,
  )
  embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
  embed.set_image(url=proof.url)

  await interaction.response.send_message(
    content = "A new run has been submitted!",
    embed=embed,
  )


def parse_time(time_str: str):
  try:
    parts = time_str.strip().split(":")

    if len(parts) == 1:
      return int(parts[0])

    elif len(parts) == 2:
      mins, secs = map(int, parts)
      if not (0 <= secs < 60):
        return None
      return mins * 60 + secs

    elif len(parts) == 3:
      hrs, mins, secs = map(int, parts)
      if not (0 <= mins < 60 and 0 <= secs < 60):
        return None
      return hrs * 3600 + mins * 60 + secs

    else:
      return None

  except ValueError:
    return None
  
def format_time(seconds: int) -> str:
  hrs = seconds // 3600
  mins = (seconds % 3600) // 60
  secs = seconds % 60

  parts = []
  if hrs > 0:
    parts.append(f"{hrs}h")
  if mins > 0:
    parts.append(f"{mins}m")
  if secs > 0 or not parts:  # ensure at least seconds show
    parts.append(f"{secs}s")

  return " ".join(parts)  

    

def record_run(user_id: int, time_seconds: int):

  # Create file if it doesn't exist
  if not os.path.exists(SPEEDRUNS_FILE):
    with open(SPEEDRUNS_FILE, "w") as f:
      json.dump([], f)

  # Load existing runs
  with open(SPEEDRUNS_FILE, "r") as f:
    runs = json.load(f)

  # Create new run
  new_run = {
    "user_id": user_id,
    "time": time_seconds,
    "date": int(time.time())  # UNIX timestamp
  }

  # Append and save
  runs.append(new_run)

  with open(SPEEDRUNS_FILE, "w") as f:
    json.dump(runs, f, indent=2)

def load_and_sort_runs():
  try:
    with open(SPEEDRUNS_FILE, "r") as f:
      runs = json.load(f)

    # sort by time ascending (fastest first)
    runs.sort(key=lambda r: r["time"])
    return runs
  
  except:
    return None


@bot.event
async def on_message(message):
  try:
    # Ignore messages from itself
    if message.author == bot.user:
      return
        
    # Only respond to messages in the target channel
    if message.channel.id not in QUOTABLE_CHANNELS:
      return
    
    # Only respond if the message contains a quote
    if {'"', '“', '”', "'", "‘", "’"}.isdisjoint(message.content):
      return
  
    print(f"A new quote was sent by {message.author}: {message.content}")

    # Scoring by LLM
    score_sum = 0
    trials = 5
    for _ in range(trials):
      result = await query_llm(LLM_QUOTE_RATING_INSTRUCTIONS, message.content)
      score_sum += float(result.splitlines()[-1])
    avg_score = round(score_sum / trials, 1)

    print(f"Scoring complete: {avg_score}")
    
    await message.reply(f"I rate this quote **{avg_score}** freaks out of 10 freakys 🤨")

  finally:
    # Important: process commands
    await bot.process_commands(message)


bot.run(TOKEN)
