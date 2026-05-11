import json
import uuid
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

_FILE = Path(__file__).parent.parent / "data" / "recurring.json"


@dataclass
class RecurringItem:
    id: str
    amount: float
    description: str
    interval_months: int
    next_due: str  # YYYY-MM-DD


def load() -> list[RecurringItem]:
    if not _FILE.exists():
        return []
    data = json.loads(_FILE.read_text())
    return [RecurringItem(**item) for item in data]


def save(items: list[RecurringItem]) -> None:
    _FILE.parent.mkdir(exist_ok=True)
    _FILE.write_text(json.dumps([asdict(i) for i in items], indent=2))


def add(amount: float, description: str, interval_months: int = 1, start_date: date | None = None) -> RecurringItem:
    if start_date is None:
        today = date.today()
        # next_due = first day of next month
        start_date = (today.replace(day=1) + relativedelta(months=1))
    item = RecurringItem(
        id=str(uuid.uuid4())[:8],
        amount=amount,
        description=description,
        interval_months=interval_months,
        next_due=start_date.isoformat(),
    )
    items = load()
    items.append(item)
    save(items)
    return item


def remove(item_id: str) -> bool:
    items = load()
    new_items = [i for i in items if i.id != item_id]
    if len(new_items) == len(items):
        return False
    save(new_items)
    return True


def get_due(reference_date: date) -> list[RecurringItem]:
    return [i for i in load() if date.fromisoformat(i.next_due) <= reference_date]


def advance(item: RecurringItem) -> RecurringItem:
    next_due = date.fromisoformat(item.next_due) + relativedelta(months=item.interval_months)
    return RecurringItem(
        id=item.id,
        amount=item.amount,
        description=item.description,
        interval_months=item.interval_months,
        next_due=next_due.isoformat(),
    )


def update_item(updated: RecurringItem) -> None:
    items = load()
    for i, item in enumerate(items):
        if item.id == updated.id:
            items[i] = updated
            break
    save(items)
