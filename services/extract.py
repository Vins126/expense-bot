import json
from datetime import date, timedelta
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


def _system_prompt() -> str:
    today = date.today()
    yesterday = today - timedelta(days=1)
    weekdays_it = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    # Last 7 days with their Italian names
    date_ref = "\n".join(
        f"- '{weekdays_it[( today - timedelta(days=i)).weekday()]}' = {(today - timedelta(days=i)).isoformat()}"
        for i in range(1, 8)
    )
    return f"""Sei un assistente per il tracciamento delle spese personali.
Estrai le informazioni di una spesa dal testo italiano fornito dall'utente.

Data di oggi: {today.isoformat()} ({weekdays_it[today.weekday()]})
Ieri: {yesterday.isoformat()}

Riferimenti giorni della settimana (usa SEMPRE la data esatta):
{date_ref}

Rispondi SOLO con un oggetto JSON valido con questi campi:
- "date": data in formato YYYY-MM-DD. Interpreta con precisione: "ieri" = {yesterday.isoformat()}, "l'altro ieri" = {(today - timedelta(days=2)).isoformat()}, giorni della settimana come da riferimento sopra, "il 3 maggio" = data del mese corrente o più recente
- "amount": importo numerico in EUR (float, senza simbolo €)
- "category": una delle seguenti categorie: {', '.join(CATEGORIES)}
- "description": descrizione breve della spesa (max 50 caratteri)

Esempio: {{"date": "{today.isoformat()}", "amount": 35.50, "category": "Alimentari", "description": "Spesa al supermercato"}}

Non aggiungere nulla oltre al JSON."""


@dataclass
class Expense:
    date: str
    amount: float
    category: str
    description: str


def extract_expense(text: str) -> Expense | None:
    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _system_prompt()},
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


def apply_edit(expense: Expense, edit_text: str) -> Expense | None:
    """Applies a free-text modification to an existing expense using AI."""
    prompt = f"""Hai questa spesa registrata:
- Data: {expense.date}
- Importo: {expense.amount}
- Categoria: {expense.category}
- Descrizione: {expense.description}

L'utente vuole modificarla con questa istruzione: "{edit_text}"

Restituisci la spesa AGGIORNATA in JSON con gli stessi campi (date, amount, category, description).
Modifica SOLO i campi indicati dall'utente, lascia invariati gli altri.
Categorie valide: {', '.join(CATEGORIES)}

Non aggiungere nulla oltre al JSON."""
    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
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
