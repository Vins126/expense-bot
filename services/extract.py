import json
import re
import base64
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
    "Salute",
    "Farmacia",
    "Psicologa",
    "Casa/Utenze",
    "Costi Fissi",
    "Intrattenimento",
    "Bellezza",
    "Regali",
    "Action",
    "Oasi",
    "EuroSpin",
    "Acqua e Sapone",
    "Altro",
]


def _date_context() -> str:
    today = date.today()
    yesterday = today - timedelta(days=1)
    weekdays_it = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    date_ref = "\n".join(
        f"- '{weekdays_it[(today - timedelta(days=i)).weekday()]}' = {(today - timedelta(days=i)).isoformat()}"
        for i in range(1, 8)
    )
    return (
        f"Data di oggi: {today.isoformat()} ({weekdays_it[today.weekday()]})\n"
        f"Ieri: {yesterday.isoformat()}\n"
        f"Riferimenti giorni della settimana:\n{date_ref}\n"
        f"Categorie valide: {', '.join(CATEGORIES)}"
    )


def _multi_system_prompt() -> str:
    today = date.today()
    return f"""Sei un assistente per il tracciamento delle finanze personali.
Estrai TUTTE le voci presenti nel testo italiano dell'utente. Possono essere spese O entrate (stipendio, rimborsi, guadagni ricevuti).

{_date_context()}

Note sulle categorie:
- Action, Pepco e Tedi → categoria "Action"
- Acquisti in farmacia/medicinali → categoria "Farmacia" (non "Salute")
- Sedute di psicologia/psicologa → categoria "Psicologa"

Rispondi SOLO con un array JSON valido. Ogni elemento ha questi campi:
- "date": data in formato YYYY-MM-DD
- "amount": importo numerico in EUR (float, sempre positivo)
- "category": una delle categorie valide (solo per spese; per entrate usa "Entrata")
- "description": descrizione breve (max 50 caratteri)
- "type": "spesa" per le spese, "entrata" per guadagni/stipendio/rimborsi ricevuti

Se c'è una sola voce, rispondi con un array di un solo elemento.
Se non ci sono voci comprensibili, rispondi con [].

Esempio con spesa e entrata: [{{"date": "{today.isoformat()}", "amount": 10.0, "category": "Ristoranti/Bar", "description": "Caffè al bar", "type": "spesa"}}, {{"date": "{today.isoformat()}", "amount": 1500.0, "category": "Entrata", "description": "Stipendio maggio", "type": "entrata"}}]

Non aggiungere nulla oltre all'array JSON."""


@dataclass
class Expense:
    date: str
    amount: float
    category: str
    description: str
    type: str = "spesa"  # "spesa" | "entrata"


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
    return match.group() if match else raw


def _parse_expenses(raw: str) -> list[Expense]:
    data = json.loads(_clean_json(raw))
    if isinstance(data, dict):
        data = [data]
    return [
        Expense(
            date=item["date"],
            amount=float(item["amount"]),
            category=item.get("category", "Altro"),
            description=item["description"],
            type=item.get("type", "spesa"),
        )
        for item in data
    ]


def extract_expenses(text: str) -> list[Expense]:
    try:
        response = _client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _multi_system_prompt()},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_expenses(raw)
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def extract_expense_from_image(image_bytes: bytes) -> list[Expense]:
    today = date.today()
    b64 = base64.b64encode(image_bytes).decode()
    prompt = f"""Sei un assistente per il tracciamento delle spese personali.
Analizza questo scontrino e raggruppa i prodotti per categoria di spesa.
{_date_context()}

Crea UNA voce per ogni categoria presente nello scontrino (non una per prodotto).
Somma gli importi dei prodotti della stessa categoria.
Usa la data dello scontrino se leggibile, altrimenti oggi.

Rispondi SOLO con un array JSON. Ogni elemento ha: date, amount, category, description.
La description deve indicare il negozio/tipo di spesa (es. "Spesa Esselunga", "Detersivi Lidl").
Se non riesci a leggere lo scontrino, rispondi con [].
Non aggiungere nulla oltre all'array JSON."""
    try:
        response = _client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0.1,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_expenses(raw)
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def apply_edit(expense: Expense, edit_text: str) -> Expense | None:
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
        data = json.loads(_clean_json(raw))
        return Expense(
            date=data["date"],
            amount=float(data["amount"]),
            category=data["category"],
            description=data["description"],
            type=expense.type,
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
