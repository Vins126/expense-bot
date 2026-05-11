import json
from datetime import datetime, date, timedelta
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID
from services.extract import Expense, CATEGORIES

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_EXPENSE_SHEET = "Spese"
_INCOME_SHEET = "Entrate"
_MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _get_client() -> gspread.Client:
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=_SCOPES)
    return gspread.authorize(creds)


def append_expense(expense: Expense) -> int:
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


def get_monthly_summary(year: int, month: int) -> dict:
    """Returns {category: total, '_total': grand_total} for the given month/year."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(_EXPENSE_SHEET)
    except gspread.WorksheetNotFound:
        return {"_total": 0.0}

    month_it = _MONTHS_IT[month]
    rows = ws.get_all_values()
    result: dict[str, float] = {}
    for row in rows[1:]:  # skip header
        if len(row) < 6:
            continue
        if row[4] == month_it and row[5] == str(year):
            try:
                amount = float(str(row[1]).replace(",", "."))
                category = row[2]
                result[category] = result.get(category, 0.0) + amount
            except ValueError:
                continue
    result["_total"] = sum(result.values())
    return result


def append_income(expense: Expense) -> None:
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(_INCOME_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=_INCOME_SHEET, rows=500, cols=5)
        ws.append_row(["Data", "Importo (€)", "Descrizione", "Mese", "Anno"])

    parsed_date = datetime.strptime(expense.date, "%Y-%m-%d")
    row = [
        parsed_date.strftime("%d/%m/%Y"),
        expense.amount,
        expense.description,
        _MONTHS_IT[parsed_date.month],
        parsed_date.year,
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def get_monthly_income(year: int, month: int) -> float:
    """Returns total income for the given month/year."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(_INCOME_SHEET)
    except gspread.WorksheetNotFound:
        return 0.0

    month_it = _MONTHS_IT[month]
    rows = ws.get_all_values()
    total = 0.0
    for row in rows[1:]:
        if len(row) < 5:
            continue
        if row[3] == month_it and row[4] == str(year):
            try:
                total += float(str(row[1]).replace(",", "."))
            except ValueError:
                continue
    return total


def get_effective_budget(year: int, month: int) -> float | None:
    """Returns monthly income if available, otherwise the manually-set budget."""
    from services.config_store import get as cfg_get
    income = get_monthly_income(year, month)
    if income > 0:
        return income
    return cfg_get("budget")


def get_weekly_summary() -> dict:
    """Returns {category: total, '_total': grand_total} for the last 7 days."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(_EXPENSE_SHEET)
    except gspread.WorksheetNotFound:
        return {"_total": 0.0}

    cutoff = date.today() - timedelta(days=7)
    rows = ws.get_all_values()
    result: dict[str, float] = {}
    for row in rows[1:]:
        if len(row) < 4:
            continue
        try:
            d = datetime.strptime(row[0], "%d/%m/%Y").date()
            if d >= cutoff:
                amount = float(str(row[1]).replace(",", "."))
                category = row[2]
                result[category] = result.get(category, 0.0) + amount
        except ValueError:
            continue
    result["_total"] = sum(result.values())
    return result


def ensure_income_sheet() -> None:
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        sh.worksheet(_INCOME_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=_INCOME_SHEET, rows=500, cols=5)
        ws.append_row(["Data", "Importo (€)", "Descrizione", "Mese", "Anno"])


def ensure_dashboard_sheet() -> None:
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet("Riepilogo")
        if ws.acell("A1").value:
            return
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Riepilogo", rows=50, cols=4)

    rows_cat = [[c, f'=SUMIF(Spese!C:C;"{c}";Spese!B:B)'] for c in CATEGORIES]
    ws.update("A1", [["--- TOTALE PER CATEGORIA ---"]], value_input_option="USER_ENTERED")
    ws.update("A2", [["Categoria", "Totale (€)"]], value_input_option="USER_ENTERED")
    ws.update("A3", rows_cat, value_input_option="USER_ENTERED")

    month_start = len(CATEGORIES) + 4
    ws.update(f"A{month_start}", [["--- TOTALE PER MESE ---"]], value_input_option="USER_ENTERED")
    ws.update(f"A{month_start+1}", [["Mese", "Totale (€)"]], value_input_option="USER_ENTERED")
    months = [
        "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]
    rows_month = [[m, f'=SUMIF(Spese!E:E;"{m}";Spese!B:B)'] for m in months]
    ws.update(f"A{month_start+2}", rows_month, value_input_option="USER_ENTERED")


def sync_dashboard_categories() -> None:
    """Adds any missing CATEGORIES rows to the Riepilogo sheet."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet("Riepilogo")
    except gspread.WorksheetNotFound:
        return

    col_a = ws.col_values(1)
    existing_cats: set[str] = set()
    month_section_row: int | None = None
    skip_values = {"--- TOTALE PER CATEGORIA ---", "--- TOTALE PER MESE ---", "Categoria", "Mese", ""}
    for i, val in enumerate(col_a):
        if val == "--- TOTALE PER MESE ---":
            month_section_row = i + 1  # 1-indexed
            break
        if val and val not in skip_values:
            existing_cats.add(val)

    if month_section_row is None:
        return

    missing = [c for c in CATEGORIES if c not in existing_cats]
    if not missing:
        return

    rows_to_insert = [[c, f'=SUMIF(Spese!C:C;"{c}";Spese!B:B)'] for c in missing]
    ws.insert_rows(rows_to_insert, row=month_section_row, value_input_option="USER_ENTERED")


def ensure_charts_sheet() -> None:
    """Creates the Grafici sheet with pie chart (categories) and bar chart (months)."""
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    try:
        riepilogo_ws = sh.worksheet("Riepilogo")
    except gspread.WorksheetNotFound:
        return

    try:
        sh.worksheet("Grafici")
        return  # already exists
    except gspread.WorksheetNotFound:
        grafici_ws = sh.add_worksheet(title="Grafici", rows=50, cols=10)

    riepilogo_id = riepilogo_ws.id
    grafici_id = grafici_ws.id

    # Categories: A3:B12 → 0-indexed rows 2-12, cols 0-2
    # Months: A16:B27 → 0-indexed rows 15-27, cols 0-2
    sh.batch_update({"requests": [
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Spese per Categoria",
                        "pieChart": {
                            "legendPosition": "RIGHT_LEGEND",
                            "domain": {"sourceRange": {"sources": [{
                                "sheetId": riepilogo_id,
                                "startRowIndex": 2, "endRowIndex": 12,
                                "startColumnIndex": 0, "endColumnIndex": 1,
                            }]}},
                            "series": {"sourceRange": {"sources": [{
                                "sheetId": riepilogo_id,
                                "startRowIndex": 2, "endRowIndex": 12,
                                "startColumnIndex": 1, "endColumnIndex": 2,
                            }]}},
                        },
                    },
                    "position": {"overlayPosition": {
                        "anchorCell": {"sheetId": grafici_id, "rowIndex": 0, "columnIndex": 0},
                        "widthPixels": 600, "heightPixels": 380,
                    }},
                }
            }
        },
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Spese per Mese",
                        "basicChart": {
                            "chartType": "COLUMN",
                            "legendPosition": "NO_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "Mese"},
                                {"position": "LEFT_AXIS", "title": "€"},
                            ],
                            "domains": [{"domain": {"sourceRange": {"sources": [{
                                "sheetId": riepilogo_id,
                                "startRowIndex": 15, "endRowIndex": 27,
                                "startColumnIndex": 0, "endColumnIndex": 1,
                            }]}}}],
                            "series": [{"series": {"sourceRange": {"sources": [{
                                "sheetId": riepilogo_id,
                                "startRowIndex": 15, "endRowIndex": 27,
                                "startColumnIndex": 1, "endColumnIndex": 2,
                            }]}}, "targetAxis": "LEFT_AXIS"}],
                        },
                    },
                    "position": {"overlayPosition": {
                        "anchorCell": {"sheetId": grafici_id, "rowIndex": 22, "columnIndex": 0},
                        "widthPixels": 600, "heightPixels": 380,
                    }},
                }
            }
        },
    ]})
