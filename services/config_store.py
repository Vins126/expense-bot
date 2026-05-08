import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_CONFIG_FILE = _DATA_DIR / "config.json"

_config: dict = {}


def load_config() -> None:
    global _config
    _DATA_DIR.mkdir(exist_ok=True)
    if _CONFIG_FILE.exists():
        _config = json.loads(_CONFIG_FILE.read_text())


def get(key: str, default=None):
    return _config.get(key, default)


def set(key: str, value) -> None:
    _config[key] = value
    _DATA_DIR.mkdir(exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(_config, indent=2))
