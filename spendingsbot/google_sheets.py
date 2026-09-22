from __future__ import annotations

import json
import logging

import gspread
from google.oauth2.service_account import Credentials

from .config import Settings
from .repository import InMemoryWorkbook, Workbook

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
]

logger = logging.getLogger(__name__)


class GoogleSheetsWorkbook(Workbook):
    def __init__(self, spreadsheet_id: str, credentials: Credentials) -> None:
        self._client = gspread.authorize(credentials)
        self._spreadsheet = self._client.open_by_key(spreadsheet_id)
        self._worksheet_cache: dict[str, object] = {}
        self._headers_ready: set[str] = set()

    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        worksheet = self._get_or_create_worksheet(title)
        current_headers = worksheet.row_values(1)
        if not current_headers:
            worksheet.update('A1', [headers], value_input_option='RAW')
            self._headers_ready.add(title.lower())
            return
        if current_headers != headers:
            raise ValueError(f'Worksheet "{title}" headers mismatch. Expected {headers}, got {current_headers}')
        self._headers_ready.add(title.lower())

    def get_rows(self, title: str) -> list[dict[str, str]]:
        worksheet = self._get_or_create_worksheet(title)
        values = worksheet.get_all_values()
        if not values:
            return []
        headers = values[0]
        rows: list[dict[str, str]] = []
        for row in values[1:]:
            padded = row + [''] * (len(headers) - len(row))
            rows.append({header: padded[index] for index, header in enumerate(headers)})
        return rows

    def replace_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        worksheet = self._get_or_create_worksheet(title)
        payload = [headers]
        for row in rows:
            payload.append([str(row.get(header, '')) for header in headers])
        worksheet.resize(rows=max(len(payload), 1), cols=max(len(headers), 1))
        worksheet.update('A1', payload, value_input_option='RAW')
        self._headers_ready.add(title.lower())

    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        worksheet = self._get_or_create_worksheet(title)
        normalized = title.lower()
        if normalized not in self._headers_ready:
            self.ensure_worksheet(title, headers)
        worksheet.append_row([str(row.get(header, '')) for header in headers], value_input_option='RAW')

    def _get_or_create_worksheet(self, title: str):
        normalized = title.lower()
        cached = self._worksheet_cache.get(normalized)
        if cached is not None:
            return cached

        for worksheet in self._spreadsheet.worksheets():
            key = worksheet.title.lower()
            self._worksheet_cache[key] = worksheet
            if key == normalized:
                return worksheet

        try:
            worksheet = self._spreadsheet.add_worksheet(title=title, rows=1000, cols=26)
            self._worksheet_cache[normalized] = worksheet
            return worksheet
        except gspread.exceptions.APIError as exc:
            if 'already exists' in str(exc).lower():
                for worksheet in self._spreadsheet.worksheets():
                    key = worksheet.title.lower()
                    self._worksheet_cache[key] = worksheet
                    if key == normalized:
                        return worksheet
            raise


def create_credentials(settings: Settings) -> Credentials:
    if settings.google_service_account_file:
        return Credentials.from_service_account_file(settings.google_service_account_file, scopes=SCOPES)
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    raise ValueError('Google service account credentials are required')


def create_workbook(settings: Settings) -> Workbook:
    try:
        credentials = create_credentials(settings)
        return GoogleSheetsWorkbook(settings.google_sheets_spreadsheet_id, credentials)
    except Exception as error:
        if not settings.allow_in_memory_fallback:
            raise RuntimeError('Failed to initialize Google Sheets workbook') from error
        logger.exception('Failed to initialize Google Sheets workbook. Falling back to in-memory storage.')
        return InMemoryWorkbook()
