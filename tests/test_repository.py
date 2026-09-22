import pytest

from spendingsbot.models import Settlement, Spending
from spendingsbot.repository import DEFAULT_MEMBER_NAMES, InMemoryWorkbook, SpendingsRepository, Workbook
from spendingsbot.settlement import calculate_settlement


@pytest.fixture()
def repository() -> SpendingsRepository:
    repo = SpendingsRepository(InMemoryWorkbook())
    repo.ensure_schema()
    return repo


def test_calculate_settlement_splits_spendings_correctly() -> None:
    result = calculate_settlement(
        ['Alice', 'Bob', 'Charlie'],
        [
            Spending(amount_eur=90, date='', description='', payer='Alice', shared_with=['Alice', 'Bob', 'Charlie']),
            Spending(amount_eur=30, date='', description='', payer='Bob', shared_with=['Bob', 'Charlie']),
        ],
    )

    assert result == [
        Settlement(from_member='Bob', to_member='Alice', amount_eur=15),
        Settlement(from_member='Charlie', to_member='Alice', amount_eur=45),
    ]


def test_trip_data_is_persisted_and_closed(repository: SpendingsRepository) -> None:
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        1,
        Spending(
            amount_eur=10,
            date='2026-09-20',
            description='Taxi',
            payer=payer,
            shared_with=[payer, participant],
        ),
    )

    before_close = repository.read_trip(1)
    assert len(before_close.spendings) == 1

    settlements = repository.close_trip(1)
    assert settlements == [Settlement(from_member=participant, to_member=payer, amount_eur=5)]

    after_close = repository.read_trip(1)
    assert after_close.trip is not None
    assert after_close.trip.closed is False


def test_storage_supports_commas_and_quotes(repository: SpendingsRepository) -> None:
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        2,
        Spending(
            amount_eur=12.5,
            date='2026-09-20',
            description='Dinner, "Pasta"',
            payer=payer,
            shared_with=[payer, participant],
        ),
    )

    state = repository.read_trip(2)
    assert state.trip is not None
    assert state.trip.name == 'Сицилия 2026'
    assert state.members == DEFAULT_MEMBER_NAMES
    assert state.spendings[0].description == 'Dinner, "Pasta"'


def test_trip_and_members_are_hardcoded(repository: SpendingsRepository) -> None:
    repository.create_trip(3, 'Trip')
    repository.create_trip(3, 'Another')

    state = repository.read_trip(3)
    assert state.trip is not None
    assert state.trip.name == 'Сицилия 2026'
    assert state.members == DEFAULT_MEMBER_NAMES

    with pytest.raises(ValueError, match='hardcoded'):
        repository.add_member(3, 'Bob')

    with pytest.raises(ValueError, match='Multiline values are not supported'):
        repository.create_trip(3, 'Trip\nName')


def test_close_trip_can_run_multiple_times(repository: SpendingsRepository) -> None:
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        4,
        Spending(
            amount_eur=10,
            date='2026-09-20',
            description='Trip transfer',
            payer=payer,
            shared_with=[payer, participant],
        ),
    )

    first = repository.close_trip(4)
    second = repository.close_trip(4)

    assert first == second


def test_calculate_settlement_handles_fractional_split_rounding() -> None:
    result = calculate_settlement(
        ['Alice', 'Bob', 'Charlie'],
        [Spending(amount_eur=10, date='', description='', payer='Alice', shared_with=['Alice', 'Bob', 'Charlie'])],
    )

    assert result == [
        Settlement(from_member='Bob', to_member='Alice', amount_eur=3.33),
        Settlement(from_member='Charlie', to_member='Alice', amount_eur=3.33),
    ]


def test_shared_with_legacy_pipe_format_is_supported(repository: SpendingsRepository) -> None:
    workbook = repository.workbook
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]
    workbook.append_row(
        repository.spendings_worksheet,
        ['chatId', 'amountEur', 'date', 'description', 'payer', 'sharedWith', 'createdAt'],
        {
            'chatId': '5',
            'amountEur': '10',
            'date': '2026-09-20',
            'description': 'Taxi',
            'payer': payer,
            'sharedWith': f'{payer}|{participant}',
            'createdAt': '',
        },
    )

    state = repository.read_trip(5)
    assert state.spendings[0].shared_with == [payer, participant]


class FailingWorkbook(Workbook):
    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        raise RuntimeError('temporary backend issue')

    def get_rows(self, title: str) -> list[dict[str, str]]:
        raise RuntimeError('temporary backend issue')

    def replace_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        raise RuntimeError('temporary backend issue')

    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        raise RuntimeError('temporary backend issue')


def test_repository_uses_memory_fallback_when_workbook_fails() -> None:
    repository = SpendingsRepository(FailingWorkbook(), allow_memory_fallback=True)

    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        6,
        Spending(
            amount_eur=22.5,
            date='2026-09-20',
            description='Groceries',
            payer=payer,
            shared_with=[payer, participant],
        ),
    )

    state = repository.read_trip(6)
    assert state.trip is not None
    assert state.trip.name == 'Сицилия 2026'
    assert state.members == DEFAULT_MEMBER_NAMES
    assert len(state.spendings) == 1
    assert state.spendings[0].description == 'Groceries'


class ReadOnlyEmptyWorkbook(Workbook):
    def ensure_worksheet(self, title: str, headers: list[str]) -> None:
        return

    def get_rows(self, title: str) -> list[dict[str, str]]:
        return []

    def replace_rows(self, title: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        raise RuntimeError('write failed')

    def append_row(self, title: str, headers: list[str], row: dict[str, str]) -> None:
        raise RuntimeError('write failed')


def test_repository_prefers_memory_rows_when_store_reads_empty() -> None:
    repository = SpendingsRepository(ReadOnlyEmptyWorkbook(), allow_memory_fallback=True)

    repository.ensure_default_trip(10, 'Сицилия 2026', ['Колян', 'Аня Д'])
    state = repository.read_trip(10)

    assert state.trip is not None
    assert state.members == DEFAULT_MEMBER_NAMES


def test_read_trip_ignores_members_sheet_and_uses_hardcoded(repository: SpendingsRepository) -> None:
    workbook = repository.workbook
    workbook.append_row(
        repository.members_worksheet,
        ['chatId', 'member', 'createdAt'],
        {'chatId': '11', 'member': 'Колян', 'createdAt': ''},
    )
    workbook.append_row(
        repository.members_worksheet,
        ['chatId', 'member', 'createdAt'],
        {'chatId': '11', 'member': 'колян', 'createdAt': ''},
    )

    state = repository.read_trip(11)
    assert state.members == DEFAULT_MEMBER_NAMES


def test_remove_last_spending_removes_latest_entry(repository: SpendingsRepository) -> None:
    payer_a = DEFAULT_MEMBER_NAMES[0]
    payer_b = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        7,
        Spending(
            amount_eur=10,
            date='2026-09-20',
            description='Coffee',
            payer=payer_a,
            shared_with=[payer_a, payer_b],
        ),
    )
    repository.add_spending(
        7,
        Spending(
            amount_eur=20,
            date='2026-09-20',
            description='Dinner',
            payer=payer_b,
            shared_with=[payer_a, payer_b],
        ),
    )

    removed = repository.remove_last_spending(7)

    assert removed.description == 'Dinner'
    state = repository.read_trip(7)
    assert len(state.spendings) == 1
    assert state.spendings[0].description == 'Coffee'


def test_remove_last_spending_can_filter_by_payer(repository: SpendingsRepository) -> None:
    payer_a = DEFAULT_MEMBER_NAMES[0]
    payer_b = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        8,
        Spending(
            amount_eur=10,
            date='2026-09-20',
            description='Taxi',
            payer=payer_a,
            shared_with=[payer_a, payer_b],
        ),
    )
    repository.add_spending(
        8,
        Spending(
            amount_eur=20,
            date='2026-09-20',
            description='Lunch',
            payer=payer_b,
            shared_with=[payer_a, payer_b],
        ),
    )
    repository.add_spending(
        8,
        Spending(
            amount_eur=30,
            date='2026-09-20',
            description='Museum',
            payer=payer_a,
            shared_with=[payer_a, payer_b],
        ),
    )

    removed = repository.remove_last_spending(8, payer_b)

    assert removed.description == 'Lunch'
    remaining_descriptions = [item.description for item in repository.read_trip(8).spendings]
    assert remaining_descriptions == ['Taxi', 'Museum']


def test_summarize_spendings_payments_scope_filters_only_payer(repository: SpendingsRepository) -> None:
    payer_a = DEFAULT_MEMBER_NAMES[0]
    payer_b = DEFAULT_MEMBER_NAMES[1]
    repository.add_spending(
        9,
        Spending(
            amount_eur=50,
            date='2026-09-20',
            description='Dinner',
            payer=payer_a,
            shared_with=[payer_a, payer_b],
        ),
    )
    repository.add_spending(
        9,
        Spending(
            amount_eur=20,
            date='2026-09-20',
            description='Taxi',
            payer=payer_b,
            shared_with=[payer_a, payer_b],
        ),
    )

    payments = repository.summarize_spendings(9, 'payments', payer_a)
    personal = repository.summarize_spendings(9, 'my', payer_a)

    assert payments['count'] == 1
    assert payments['total_eur'] == 50
    assert payments['spendings'][0].description == 'Dinner'
    assert personal['count'] == 2


def test_add_spending_rejects_invalid_amount(repository: SpendingsRepository) -> None:
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]

    with pytest.raises(ValueError, match='positive finite'):
        repository.add_spending(
            12,
            Spending(
                amount_eur=0,
                date='2026-09-20',
                description='Bad amount',
                payer=payer,
                shared_with=[payer, participant],
            ),
        )


def test_add_spending_rejects_invalid_date(repository: SpendingsRepository) -> None:
    payer = DEFAULT_MEMBER_NAMES[0]
    participant = DEFAULT_MEMBER_NAMES[1]

    with pytest.raises(ValueError, match='YYYY-MM-DD'):
        repository.add_spending(
            13,
            Spending(
                amount_eur=10,
                date='20-09-2026',
                description='Bad date',
                payer=payer,
                shared_with=[payer, participant],
            ),
        )
