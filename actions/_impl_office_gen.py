from __future__ import annotations

from actions._common import ask_json, log, open_path, output_dir, safe_name, unique_path
from actions import _impl_office as ob

SYSTEM = (
    "You design Excel workbooks. Reply with ONE JSON object and nothing else, matching: "
    '{"theme": "blue"|"green"|"dark"|"mono"|"sunset", "sheets": [{"name": str, "title": str, "subtitle": str, '
    '"columns": [{"header": str, "format": "text"|"integer"|"number"|"currency"|"percent"|"date", "width": number}], '
    '"rows": [[value, ...]], "totals": {"label": str, "columns": {"C": "sum"|"avg"|"min"|"max"|"count"}}, '
    '"charts": [{"type": "bar"|"line"|"pie", "title": str, "data_cols": ["C"], "cat_col": "A"}], '
    '"conditional": [{"column": "D", "rule": "gt"|"lt"|"ge"|"le"|"eq", "value": number, "color": "C6EFCE"}]}]}. '
    "Rules: use REAL Excel formulas for every calculated cell (a string starting with '='; write {row} where the "
    "current row number belongs, e.g. \"=B{row}*C{row}\"); never hard-code a computed result. Include realistic "
    "sample rows (8-15) unless the user supplied data; add a totals row when sums make sense; add one chart when "
    "it helps; percentages as fractions (0.15 = 15%). Column letters in totals/charts must match the columns. "
    "Write in the requested language."
)


def generate_spreadsheet(parameters: dict, player=None, speak=None) -> str:
    if not ob._XL:
        return ob.need("openpyxl")
    p = parameters or {}
    desc = str(p.get("description") or "").strip()
    if not desc:
        return "Sir, describe the spreadsheet you need."
    log(f"[Excel] Designing: {desc[:80]}", player)
    spec = ask_json(f"Build this spreadsheet: {desc}\nLanguage: {p.get('language') or 'same as the request'}\n"
                    f"Preferred theme: {p.get('theme') or 'any'}", SYSTEM, default=None)
    if not isinstance(spec, dict) or not spec.get("sheets"):
        return "Sir, I couldn't design that spreadsheet right now. Please try again."
    if p.get("theme"):
        spec["theme"] = p["theme"]
    title = str(spec["sheets"][0].get("title") or desc[:40])
    path = unique_path(output_dir("Spreadsheets"), safe_name(p.get("filename") or title, "spreadsheet"), ".xlsx")
    try:
        n = ob.build_workbook(spec, path)
    except Exception as e:
        return f"Sir, building the spreadsheet failed: {e}"
    log(f"[Excel] Saved {path}", player)
    if p.get("open_after", True):
        open_path(path)
    return f"Spreadsheet ready, sir: '{title}', {n} sheet(s) with live formulas. Saved to {path}."


TOOL = {
    "name": "generate_spreadsheet",
    "description": (
        "Designs and creates a complete Excel (.xlsx) spreadsheet from a plain-language description: budgets, "
        "expense or habit trackers, invoices, grade books, schedules, inventories, project plans, financial "
        "reports. Includes working formulas, totals, formatting and charts. Use when the user describes what "
        "they want a spreadsheet for."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description": {"type": "STRING", "description": "What the spreadsheet is for and what it must contain"},
            "theme": {"type": "STRING", "description": "blue | green | dark | mono | sunset"},
            "language": {"type": "STRING", "description": "Language of labels"},
            "filename": {"type": "STRING", "description": "Optional file name"},
            "open_after": {"type": "BOOLEAN", "description": "Open the file when done (default true)"},
        },
        "required": ["description"],
    },
    "handler": generate_spreadsheet,
}

# by ASDcuber521
