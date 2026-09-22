from spendingsbot.parsers import (
    get_command_args,
    is_valid_iso_date,
    parse_shared_members,
    split_spending_arguments,
)


def test_get_command_args_removes_only_command_token() -> None:
    assert get_command_args('/newtrip my /newtrip plan') == 'my /newtrip plan'
    assert get_command_args('/addmember') == ''


def test_split_spending_arguments_requires_exactly_five_fields() -> None:
    assert split_spending_arguments('10;2026-09-20;Dinner;late;Alice;Bob') is None
    assert split_spending_arguments('10; 2026-09-20; Dinner; Alice; Bob,Charlie') == [
        '10',
        '2026-09-20',
        'Dinner',
        'Alice',
        'Bob,Charlie',
    ]


def test_split_spending_arguments_treats_semicolon_as_reserved_separator() -> None:
    assert split_spending_arguments('10; 2026-09-20; Dinner; late; Alice; Bob') is None


def test_is_valid_iso_date_validates_real_calendar_dates() -> None:
    assert is_valid_iso_date('2026-02-28') is True
    assert is_valid_iso_date('2026-02-31') is False
    assert is_valid_iso_date('2026-99-99') is False


def test_parse_shared_members_supports_quoted_commas() -> None:
    assert parse_shared_members('"Alice, A",Bob') == ['Alice, A', 'Bob']
    assert parse_shared_members('"Alice ""The A"" , A",Bob') == ['Alice "The A" , A', 'Bob']
    assert parse_shared_members('"Alice,Bob') is None
