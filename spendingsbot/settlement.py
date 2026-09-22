from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .models import Settlement, Spending


def _amount_to_cents(amount_eur: float) -> int:
    return int((Decimal(str(amount_eur)) * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def calculate_settlement(members: list[str], spendings: list[Spending]) -> list[Settlement]:
    balances_in_cents = {member: 0 for member in members}

    for spending in spendings:
        if not spending.shared_with:
            raise ValueError('Spending has empty shared members')

        amount_in_cents = _amount_to_cents(spending.amount_eur)
        split_base = amount_in_cents // len(spending.shared_with)
        remainder = amount_in_cents - split_base * len(spending.shared_with)

        balances_in_cents[spending.payer] += amount_in_cents
        for member in spending.shared_with:
            share = split_base + (1 if remainder > 0 else 0)
            balances_in_cents[member] -= share
            if remainder > 0:
                remainder -= 1

    creditors: list[dict[str, int | str]] = []
    debtors: list[dict[str, int | str]] = []

    for member, balance in balances_in_cents.items():
        if balance > 0:
            creditors.append({'member': member, 'amount': balance})
        elif balance < 0:
            debtors.append({'member': member, 'amount': -balance})

    settlements: list[Settlement] = []
    debtor_index = 0
    creditor_index = 0

    while debtor_index < len(debtors) and creditor_index < len(creditors):
        debtor = debtors[debtor_index]
        creditor = creditors[creditor_index]
        payment = min(int(debtor['amount']), int(creditor['amount']))
        settlements.append(
            Settlement(
                from_member=str(debtor['member']),
                to_member=str(creditor['member']),
                amount_eur=payment / 100,
            )
        )

        debtor['amount'] = int(debtor['amount']) - payment
        creditor['amount'] = int(creditor['amount']) - payment

        if debtor['amount'] == 0:
            debtor_index += 1
        if creditor['amount'] == 0:
            creditor_index += 1

    return settlements
