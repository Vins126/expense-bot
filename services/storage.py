import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_USERS_FILE = _DATA_DIR / "users.json"

_users: set[int] = set()


def initialize_users(initial: set[int]) -> None:
    global _users
    _DATA_DIR.mkdir(exist_ok=True)
    if _USERS_FILE.exists():
        _users = set(json.loads(_USERS_FILE.read_text()))
    else:
        _users = set(initial)
        _save()


def get_users() -> set[int]:
    return _users


def add_user(user_id: int) -> None:
    _users.add(user_id)
    _save()


def remove_user(user_id: int) -> bool:
    if user_id not in _users:
        return False
    _users.discard(user_id)
    _save()
    return True


def _save() -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _USERS_FILE.write_text(json.dumps(list(_users)))
