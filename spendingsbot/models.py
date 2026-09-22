from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TripInfo:
    name: str
    closed: bool


@dataclass(slots=True)
class Spending:
    amount_eur: float
    date: str
    description: str
    payer: str
    shared_with: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Settlement:
    from_member: str
    to_member: str
    amount_eur: float


@dataclass(slots=True)
class TripState:
    trip: TripInfo | None
    members: list[str]
    spendings: list[Spending]
