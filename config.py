import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Variabile d'ambiente mancante: {key}")
    return value


BOT_TOKEN: str = _require("BOT_TOKEN")
GROQ_API_KEY: str = _require("GROQ_API_KEY")
GOOGLE_CREDENTIALS_JSON: str = _require("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID: str = _require("SPREADSHEET_ID")
AUTHORIZED_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in _require("AUTHORIZED_USER_IDS").split(",")
}
ADMIN_USER_ID: int = int(_require("ADMIN_USER_ID"))
