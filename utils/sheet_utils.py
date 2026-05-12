import gspread, asyncio
from gspread import Spreadsheet, Worksheet
from google.oauth2.service_account import Credentials
from config import *

__all__ = ["get_spreadsheet", "get_worksheet", "add_row"]

SCOPES = [
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/drive",
]

# Authenticate once when the module is imported
_creds = Credentials.from_service_account_file(GOOGLE_CRED_FILE, scopes=SCOPES)
_client = gspread.authorize(_creds)


def get_spreadsheet(url: str) -> Spreadsheet:
  return _client.open_by_url(url)


def get_worksheet(spreadsheet: Spreadsheet, worksheet: str) -> Worksheet:
  return spreadsheet.worksheet(worksheet)


async def add_row(worksheet: Worksheet, row: list) -> None:
  return await asyncio.to_thread(worksheet.append_row, row)