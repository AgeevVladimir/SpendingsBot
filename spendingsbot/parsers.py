from __future__ import annotations

from datetime import date


def get_command_args(text: str) -> str:
    first_space = text.find(' ')
    return '' if first_space == -1 else text[first_space + 1 :].strip()


def split_spending_arguments(raw: str) -> list[str] | None:
    if raw.count(';') != 4:
        return None
    parts = [part.strip() for part in raw.split(';')]
    if len(parts) != 5:
        return None
    return parts


def is_valid_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def parse_shared_members(shared_raw: str) -> list[str] | None:
    members: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0

    while i < len(shared_raw):
        ch = shared_raw[i]
        if ch == '"':
            if in_quotes and i + 1 < len(shared_raw) and shared_raw[i + 1] == '"':
                current.append('"')
                i += 1
            else:
                in_quotes = not in_quotes
            i += 1
            continue

        if ch == ',' and not in_quotes:
            value = ''.join(current).strip()
            if value:
                members.append(value)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    if in_quotes:
        return None

    value = ''.join(current).strip()
    if value:
        members.append(value)
    return members
