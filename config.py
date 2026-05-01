# Channel that every feature is allowed in, for testing
TESTING_CHANNEL = 923084109578899456

# List of channels allowed for the snipe command (channel ID)
SNIPEABLE_CHANNELS = [TESTING_CHANNEL]

# List of quote channels to be evaluated for freakiness
QUOTABLE_CHANNELS = [TESTING_CHANNEL, 761018278604570665]

# List of channels allowed for speedrun submits
SPEEDRUN_SUBMIT_CHANNELS = [TESTING_CHANNEL, 1495241749453476050]

# File to save speedrun data
SPEEDRUNS_FILE = "speedrun_records.json"

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