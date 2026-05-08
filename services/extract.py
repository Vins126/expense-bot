import json
from datetime import date
from dataclasses import dataclass
from groq import Groq
from config import GROQ_API_KEY

_client = Groq(api_key=GROQ_API_KEY)

CATEGORIES = [
    "Alimentari",
    "Ristoranti/Bar",
    "Trasporti",
    "Abbigliamento",
    "Salute/Farmacia",
    "Casa/Utenze",
    "Intrattenimento",
    "Bellezza",
    "Regali",
    "Altro",
]

_SYSTEM_PROMPT = f"""Sei un assistente per il tracciamento delle spese personali.
Estrai le informazioni di una spesa dal testo italiano fornito dall'utente.

Rispondi SOLO con un oggetto JSON valido con questi campi:
- "date": data in formato YYYY-MM-DD (usa la data di oggi se non specificata: {date.today().isoformat()})
- "amount": importo numerico in EUR (float, senza simbolo €)
- "category": una delle seguenti categorie: {', '.join(CATEGORIES)}
- "description": descrizione breve della spesa (max 50 caratteri)

Esempio di risposta:
{{"date": "{date.today().isoformat()}", "amount": 35.50, "category": "Alimentari", "description": "Spesa al supermercato"}}

Non aggiungere nulla oltre al JSON."""


@dataclass
class Expense:
    date: str
    amount: float
    category: str
    description: str


def extract_expense(text: str) -> Expense | None:
    """Extracts structured expense data from Italian text. Returns None if extraction fails."""
    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return Expense(
            date=data["date"],
            amount=float(data["amount"]),
            category=data["category"],
            description=data["description"],
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
