from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, date, datetime
from threading import Lock
from typing import Iterator

from .models import Settlement, Spending, TripInfo, TripState
from .settlement import calculate_settlement

TRIPS_HEADERS = ['chatId', 'tripName', 'closed', 'createdAt']
MEMBERS_HEADERS = ['chatId', 'member', 'createdAt']
SPENDINGS_HEADERS = ['chatId', 'amountEur', 'date', 'description', 'payer', 'sharedWith', 'createdAt']

DEFAULT_TRIP_NAME = 'Сицилия 2026'
DEFAULT_MEMBER_NAMES = [
    'Вовчик',
    'Аня Д',
    'Дэнчик',
    'Лиза',
    'Наташа',
    'Артем',
    'Колян',
    'Аня Б',
]


class Workbook(ABC):
    @abstractmethod
    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_rows(self, title: str) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def replace_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        raise NotImplementedError


class InMemoryWorkbook(Workbook):
    def __init__(self) -> None:
        self._headers: dict[str, list[str]] = {}
        self._rows: dict[str, list[dict[str, str]]] = {}

    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        self._headers.setdefault(title, list(headers))
        self._rows.setdefault(title, [])

    def get_rows(self, title: str) -> list[dict[str, str]]:
        return [row.copy() for row in self._rows.get(title, [])]

    def replace_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        self._headers[title] = list(headers)
        self._rows[title] = [
            {header: str(row.get(header, '')) for header in headers}
            for row in rows
        ]

    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        self.ensure_worksheet(title, headers)
        self._rows[title].append({header: str(row.get(header, '')) for header in headers})


class SpendingsRepository:
    def __init__(
        self,
        workbook: Workbook,
        trips_worksheet: str = 'trips',
        members_worksheet: str = 'members',
        spendings_worksheet: str = 'spendings',
        allow_memory_fallback: bool = False,
    ) -> None:
        self.workbook = workbook
        self.trips_worksheet = trips_worksheet
        self.members_worksheet = members_worksheet
        self.spendings_worksheet = spendings_worksheet
        self.allow_memory_fallback = allow_memory_fallback
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()
        self._memory_rows: dict[str, list[dict[str, str]]] = {
            trips_worksheet: [],
            members_worksheet: [],
            spendings_worksheet: [],
        }

    @staticmethod
    def _hardcoded_members() -> list[str]:
        members: list[str] = []
        seen: set[str] = set()
        for member in DEFAULT_MEMBER_NAMES:
            clean = (member or '').strip()
            if not clean:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            members.append(clean)
        return members

    def ensure_schema(self) -> None:
        try:
            self.workbook.ensure_worksheet(self.spendings_worksheet, SPENDINGS_HEADERS)
        except Exception:
            if not self.allow_memory_fallback:
                raise
            self._memory_rows.setdefault(self.spendings_worksheet, [])

    def _get_rows_from_store(self, title: str) -> list[dict[str, str]]:
        try:
            rows = self.workbook.get_rows(title)
            if rows:
                return rows
            if not self.allow_memory_fallback:
                return rows
        except Exception:
            if not self.allow_memory_fallback:
                raise
        return [row.copy() for row in self._memory_rows.get(title, [])]

    def _replace_rows_in_store(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        try:
            self.workbook.replace_rows(title, headers, rows)
        except Exception:
            if not self.allow_memory_fallback:
                raise
            self._memory_rows[title] = [
                {header: str(row.get(header, '')) for header in headers}
                for row in rows
            ]

    def _append_row_in_store(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        try:
            self.workbook.append_row(title, headers, row)
        except Exception:
            if not self.allow_memory_fallback:
                raise
            self._memory_rows.setdefault(title, [])
            self._memory_rows[title].append({header: str(row.get(header, '')) for header in headers})

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @contextmanager
    def _chat_lock(self, chat_id: int | str) -> Iterator[None]:
        key = str(chat_id)
        with self._locks_guard:
            lock = self._locks.setdefault(key, Lock())
        with lock:
            yield

    @staticmethod
    def _validate_single_line(*values: str) -> None:
        for value in values:
            text = str(value)
            if '\n' in text or '\r' in text:
                raise ValueError('Multiline values are not supported in storage')

    @staticmethod
    def _validate_spending(spending: Spending) -> None:
        if not math.isfinite(spending.amount_eur) or spending.amount_eur <= 0:
            raise ValueError('Amount must be a positive finite number')
        try:
            date.fromisoformat(spending.date)
        except ValueError as error:
            raise ValueError('Date must be in format YYYY-MM-DD') from error

    @staticmethod
    def _parse_shared_with_field(value: str) -> list[str]:
        if not value:
            return []
        if value.startswith('['):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError('Invalid sharedWith data in storage') from error
            if not isinstance(parsed, list):
                raise ValueError('Invalid sharedWith data in storage')
            return [str(item) for item in parsed]
        return value.split('|')

    def read_trip(self, chat_id: int | str) -> TripState:
        self.ensure_schema()
        spending_rows = self._get_rows_from_store(self.spendings_worksheet)

        trip = TripInfo(name=DEFAULT_TRIP_NAME, closed=False)
        members = self._hardcoded_members()
        spendings = [
            Spending(
                amount_eur=float(row.get('amountEur', '0') or 0),
                date=row.get('date', ''),
                description=row.get('description', ''),
                payer=row.get('payer', ''),
                shared_with=self._parse_shared_with_field(row.get('sharedWith', '')),
            )
            for row in spending_rows
        ]

        return TripState(trip=trip, members=members, spendings=spendings)

    def create_trip(self, chat_id: int | str, name: str) -> None:
        self._validate_single_line(name)
        return

    def add_member(self, chat_id: int | str, member_name: str) -> None:
        self._validate_single_line(member_name)
        raise ValueError('Members are hardcoded and cannot be changed')

    def add_spending(self, chat_id: int | str, spending: Spending) -> None:
        self.ensure_schema()
        self._validate_single_line(spending.description, spending.payer, *spending.shared_with)
        self._validate_spending(spending)
        with self._chat_lock(chat_id):
            state = self.read_trip(chat_id)
            if not spending.shared_with:
                raise ValueError('At least one shared member is required')

            unknown_members = [member for member in spending.shared_with if member not in state.members]
            if spending.payer not in state.members or unknown_members:
                raise ValueError('All payer and shared members must be added first')

            self._append_row_in_store(
                self.spendings_worksheet,
                SPENDINGS_HEADERS,
                {
                    'chatId': str(chat_id),
                    'amountEur': str(spending.amount_eur),
                    'date': spending.date,
                    'description': spending.description,
                    'payer': spending.payer,
                    'sharedWith': json.dumps(spending.shared_with),
                    'createdAt': self._timestamp(),
                },
            )

    def close_trip(self, chat_id: int | str) -> list[Settlement]:
        state = self.read_trip(chat_id)
        return calculate_settlement(state.members, state.spendings)

    def ensure_default_trip(
        self,
        chat_id: int | str,
        trip_name: str = DEFAULT_TRIP_NAME,
        default_members: list[str] | tuple[str, ...] | None = None,
    ) -> TripState:
        self._validate_single_line(trip_name)
        if default_members is not None:
            self._validate_single_line(*[str(member) for member in default_members])
        return self.read_trip(chat_id)

    def summarize_spendings(
        self,
        chat_id: int | str,
        scope: str = 'all',
        member_name: str | None = None,
        date_value: str | None = None,
    ) -> dict:
        state = self.read_trip(chat_id)

        spendings = list(state.spendings)
        normalized_scope = (scope or 'all').lower()

        if normalized_scope == 'today':
            target_day = date_value or datetime.now(UTC).date().isoformat()
            spendings = [item for item in spendings if item.date == target_day]
        elif normalized_scope == 'my':
            if member_name:
                spendings = [
                    item
                    for item in spendings
                    if item.payer == member_name or member_name in item.shared_with
                ]
        elif normalized_scope == 'payments':
            if member_name:
                spendings = [item for item in spendings if item.payer == member_name]

        total = sum(item.amount_eur for item in spendings)
        return {
            'scope': normalized_scope,
            'total_eur': round(total, 2),
            'count': len(spendings),
            'member': member_name,
            'date': date_value,
            'spendings': spendings,
        }

    def remove_last_spending(self, chat_id: int | str, payer: str | None = None) -> Spending:
        self.ensure_schema()
        with self._chat_lock(chat_id):
            rows = self._get_rows_from_store(self.spendings_worksheet)
            if not rows:
                raise ValueError('No spendings to undo')

            target_index = -1
            if payer:
                for index in range(len(rows) - 1, -1, -1):
                    if rows[index].get('payer', '') == payer:
                        target_index = index
                        break
            else:
                target_index = len(rows) - 1

            if target_index < 0:
                raise ValueError(f'No spendings by {payer} to undo')

            removed = rows.pop(target_index)
            self._replace_rows_in_store(self.spendings_worksheet, SPENDINGS_HEADERS, rows)

            return Spending(
                amount_eur=float(removed.get('amountEur', '0') or 0),
                date=removed.get('date', ''),
                description=removed.get('description', ''),
                payer=removed.get('payer', ''),
                shared_with=self._parse_shared_with_field(removed.get('sharedWith', '')),
            )
