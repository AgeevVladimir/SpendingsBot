from __future__ import annotations

import json

import gspread
from google.oauth2.service_account import Credentials

from .config import Settings
from .repository import InMemoryWorkbook, Workbook

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
]


class GoogleSheetsWorkbook(Workbook):
    def __init__(self, spreadsheet_id: str, credentials: Credentials) -> None:
        self._client = gspread.authorize(credentials)
        self._spreadsheet = self._client.open_by_key(spreadsheet_id)

    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        worksheet = self._get_or_create_worksheet(title)
        values = worksheet.get_all_values()
        if not values:
            worksheet.append_row(headers, value_input_option='RAW')
            return
        current_headers = values[0]
        if current_headers != headers:
            worksheet.clear()
            worksheet.update('A1', [headers], value_input_option='RAW')

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
        worksheet.clear()
        worksheet.update('A1', payload, value_input_option='RAW')

    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        worksheet = self._get_or_create_worksheet(title)
        if not worksheet.get_all_values():
            worksheet.append_row(headers, value_input_option='RAW')
        worksheet.append_row([str(row.get(header, '')) for header in headers], value_input_option='RAW')

    def _get_or_create_worksheet(self, title: str):
        normalized = title.lower()
        for worksheet in self._spreadsheet.worksheets():
            if worksheet.title.lower() == normalized:
                return worksheet

        try:
            return self._spreadsheet.add_worksheet(title=title, rows=1000, cols=26)
        except gspread.exceptions.APIError as exc:
            if 'already exists' in str(exc).lower():
                for worksheet in self._spreadsheet.worksheets():
                    if worksheet.title.lower() == normalized:
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
    except Exception:
        return InMemoryWorkbook()
