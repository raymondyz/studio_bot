from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# JSON file that contains google credentials (for spreads)
GOOGLE_CRED_FILE = BASE_DIR / "credentials.json"


# Channel that every feature is allowed in, for testing
TESTING_CHANNEL = 923084109578899456

# ========== SPEEDRUN ==========

# List of channels allowed for speedrun submits
SPEEDRUN_SUBMIT_CHANNELS = [TESTING_CHANNEL, 1495241749453476050]

# File to save speedrun data
SPEEDRUNS_FILE = DATA_DIR / "speedruns.json"

# ========== SNIPES ==========

# List of channels allowed for the snipe command (channel ID)
SNIPEABLE_CHANNELS = [TESTING_CHANNEL]

# List of roles that can snipe and be sniped (role ID)
SNIPEABLE_ROLES = [1501067436932337684, 533145974370074624, 1039004465237336064]

# Snipe Spreadsheet Link
SNIPE_SPREAD_LINK="https://docs.google.com/spreadsheets/d/1yDKo0W_NaOCnEukhLyhHt_rG_FD08xfPnwEnhtc1McA/"

# Snipe Log Worksheet Name
SNIPE_LOG_SHEET_NAME="Snipes"

# ========== QUOTE RATING ==========

# List of quote channels to be evaluated for freakiness
QUOTABLE_CHANNELS = [TESTING_CHANNEL, 761018278604570665, 1509761469414375544]

# ========== MODERATION ==========

# Channel to log bans in
LOGGING_CHANNEL = 533146727130071042

# Channels to check for spam
SPAM_CHECK_CHANNELS = [
  877411163279872030,
  1295471164486848523,
  877409573068242974,
  571900022275440640,
  532049833263890433,
  905316314711752714,
  763433902713995265,
  537484366528643102
]

# How many identical messages must be sent by the same user within a short period to trigger a ban
SPAM_THRESHOLD = 3

# Who to contact about bot issues
DEVELOPER_CONTACT = "Raymond Z (Discord: raymond.z)"