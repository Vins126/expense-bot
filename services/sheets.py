import json
from datetime import datetime
from typing import NamedTuple
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID
from services.extract import Expense

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_EXPENSE_SHEET = "Spese"
_MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _get_client() -> gspread.Client:
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    return gspread.authorize(creds)


def append_expense(expense: Expense) -> int:
    """Appends an expense row to Google Sheets. Returns the row number."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(_EXPENSE_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=_EXPENSE_SHEET, rows=1000, cols=6)
        ws.append_row(["Data", "Importo (€)", "Categoria", "Descrizione", "Mese", "Anno"])

    parsed_date = datetime.strptime(expense.date, "%Y-%m-%d")
    row = [
        parsed_date.strftime("%d/%m/%Y"),
        expense.amount,
        expense.category,
        expense.description,
        _MONTHS_IT[parsed_date.month],
        parsed_date.year,
    ]
    result = ws.append_row(row, value_input_option="USER_ENTERED")
    updates = result.get("updates", {})
    return updates.get("updatedRange", "").split(":")[-1]


def ensure_dashboard_sheet() -> None:
    """Creates the Riepilogo sheet with SUMIF formulas if it doesn't exist or is empty."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet("Riepilogo")
        if ws.acell("A1").value:
            return
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Riepilogo", rows=30, cols=4)

    headers_cat = [["Categoria", "Totale (€)"]]
    categories = [
        "Alimentari", "Ristoranti/Bar", "Trasporti", "Abbigliamento",
        "Salute/Farmacia", "Casa/Utenze", "Intrattenimento", "Bellezza",
        "Regali", "Altro",
    ]
    rows_cat = [[c, f'=SUMIF(Spese!C:C;A{i+3};Spese!B:B)'] for i, c in enumerate(categories)]
    ws.update("A1", [["--- TOTALE PER CATEGORIA ---"]], value_input_option="USER_ENTERED")
    ws.update("A2", headers_cat, value_input_option="USER_ENTERED")
    ws.update("A3", rows_cat, value_input_option="USER_ENTERED")

    month_start = len(categories) + 4
    ws.update(f"A{month_start}", [["--- TOTALE PER MESE ---"]], value_input_option="USER_ENTERED")
    ws.update(f"A{month_start+1}", [["Mese", "Totale (€)"]], value_input_option="USER_ENTERED")
    months = [
        "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]
    rows_month = [[m, f'=SUMIF(Spese!E:E;A{month_start+2+i};Spese!B:B)'] for i, m in enumerate(months)]
    ws.update(f"A{month_start+2}", rows_month, value_input_option="USER_ENTERED")
