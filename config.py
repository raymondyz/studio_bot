from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# File to save speedrun data
SPEEDRUNS_FILE = DATA_DIR / "speedruns.json"

# Channel that every feature is allowed in, for testing
TESTING_CHANNEL = 923084109578899456

# List of channels allowed for the snipe command (channel ID)
SNIPEABLE_CHANNELS = [TESTING_CHANNEL]

# List of roles that can snipe and be sniped (role ID)
SNIPEABLE_ROLES = [1501067436932337684, 533145974370074624, 1039004465237336064]

# List of quote channels to be evaluated for freakiness
QUOTABLE_CHANNELS = [TESTING_CHANNEL, 761018278604570665]

# List of channels allowed for speedrun submits
SPEEDRUN_SUBMIT_CHANNELS = [TESTING_CHANNEL, 1495241749453476050]