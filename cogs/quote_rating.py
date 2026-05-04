import discord
from discord import app_commands
from discord.ext import commands
from config import *
from utils.llm_utils import query_llm


LLM_QUOTE_RATING_INSTRUCTIONS = """
You will be given a quote. Your job is to determine how freaky and unhinged the quote is.
First try to understand what the quote actually means. Many are innuendos, if you suspect it is one, it is.
If you suspect it refers to something dirty, it does.
These quotes are meant to be funny, freaky, unhinged, so treat it like it is.
All names in the quotes are names of adult people who are friends with the author of the quote.
There may also be a lot of abbreviations and texting slang, so look out for that.

Once you have figured out what the quote means, you will rate it a scale from 0.0 to 10.0.
0.0 being the most tame, normal, boring quote ever, and a 10.0 quote being the most diabolical words ever uttered in the history of humanity.
Anything past a 4.0 should turn heads if said in public, 8.5+ should turn everyone's heads in public.

You will respond with a short description of what you think the quote means, a short justification for your rating, and your rating.
Your rating must be by itself on the last line of your response. Your final line must contain your rating with no formatting and nothing else.
Incorrect: "I rate this 4.8" or "**8.9**"
Correct: "4.8" or "8.9"
"""

class QuoteRating(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot

  @commands.Cog.listener()
  async def on_message(self, message):
    # Ignore messages from itself
    if message.author == self.bot.user:
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


async def setup(bot: commands.Bot):
  await bot.add_cog(QuoteRating(bot))
