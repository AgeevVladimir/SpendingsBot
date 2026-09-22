from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    google_sheets_spreadsheet_id: str
    google_service_account_file: str | None = None
    google_service_account_json: str | None = None
    allow_in_memory_fallback: bool = False
    google_sheets_trips_worksheet: str = 'trips'
    google_sheets_members_worksheet: str = 'members'
    google_sheets_spendings_worksheet: str = 'spendings'


def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv('BOT_TOKEN', '').strip()
    spreadsheet_id = os.getenv('GOOGLE_SHEETS_SPREADSHEET_ID', '').strip()
    service_account_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', '').strip() or None
    service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip() or None
    allow_in_memory_fallback = os.getenv('ALLOW_IN_MEMORY_FALLBACK', '').strip().lower() in {'1', 'true', 'yes', 'on'}

    if not bot_token:
        raise ValueError('BOT_TOKEN is required')
    if not spreadsheet_id:
        raise ValueError('GOOGLE_SHEETS_SPREADSHEET_ID is required')
    if not service_account_file and not service_account_json:
        raise ValueError('Set GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON')

    return Settings(
        bot_token=bot_token,
        google_sheets_spreadsheet_id=spreadsheet_id,
        google_service_account_file=service_account_file,
        google_service_account_json=service_account_json,
        allow_in_memory_fallback=allow_in_memory_fallback,
        google_sheets_trips_worksheet=os.getenv('GOOGLE_SHEETS_TRIPS_WORKSHEET', 'trips').strip() or 'trips',
        google_sheets_members_worksheet=os.getenv('GOOGLE_SHEETS_MEMBERS_WORKSHEET', 'members').strip() or 'members',
        google_sheets_spendings_worksheet=os.getenv('GOOGLE_SHEETS_SPENDINGS_WORKSHEET', 'spendings').strip() or 'spendings',
    )
