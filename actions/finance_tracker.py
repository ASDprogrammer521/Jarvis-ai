from __future__ import annotations

import uuid
from datetime import date, datetime

from actions._common import DATA_DIR, cfg, json_load, json_save, log, open_path, output_dir, safe_name, unique_path

STORE = DATA_DIR / "finance.json"
KEYWORDS = {
    "Food": ("food", "lunch", "dinner", "breakfast", "cafe", "coffee", "restaurant", "grocer", "market", "bread", "pizza", "plov", "meal"),
    "Transport": ("taxi", "bus", "metro", "fuel", "gas", "petrol", "uber", "yandex", "parking", "train", "flight", "ticket"),
    "Bills": ("rent", "electric", "water bill", "internet", "phone", "bill", "utilities", "subscription", "insurance"),
    "Shopping": ("shop", "clothes", "shoes", "amazon", "gadget", "gift", "mall", "bought"),
    "Health": ("doctor", "pharmacy", "medicine", "gym", "dentist", "hospital", "vitamin"),
    "Fun": ("movie", "game", "cinema", "concert", "netflix", "spotify", "party", "bar", "trip"),
    "Education": ("course", "book", "school", "university", "tuition", "class"),
}


def _guess(note: str) -> str:
    n = (note or "").lower()
    for cat, words in KEYWORDS.items():
        if any(w in n for w in words):
            return cat
    return "Other"


def _month(m) -> str:
    s = str(m or "").strip().lower()
    t = date.today()
    if s in ("", "this month", "current", "now"):
        return t.strftime("%Y-%m")
    if s in ("last month", "previous"):
        y, mo = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
        return f"{y}-{mo:02d}"
    datetime.strptime(s, "%Y-%m")
    return s


def _money(v: float, cur: str) -> str:
    return f"{v:,.2f} {cur}" if abs(v) < 1000 or v != int(v) else f"{v:,.0f} {cur}"


def _summary(data: dict, month: str, cur: str) -> tuple:
    ents = [e for e in data["entries"] if e["date"].startswith(month)]
    exp = {}
    inc = 0.0
    for e in ents:
        if e["type"] == "income":
            inc += e["amount"]
        else:
            exp[e["category"]] = exp.get(e["category"], 0) + e["amount"]
    total = sum(exp.values())
    lines = [f"Finances for {month}:", f"Income: {_money(inc, cur)}", f"Spent: {_money(total, cur)}", f"Balance: {_money(inc - total, cur)}"]
    for cat, v in sorted(exp.items(), key=lambda kv: -kv[1]):
        b = data["budgets"].get(cat)
        flag = f"  (budget {_money(b, cur)} — {'OVER by ' + _money(v - b, cur) if v > b else str(round(v / b * 100)) + '% used'})" if b else ""
        lines.append(f"• {cat}: {_money(v, cur)} ({v / total * 100:.0f}%){flag}" if total else f"• {cat}: {_money(v, cur)}")
    return ents, "\n".join(lines), total, inc


def finance_tracker(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "summary").lower().strip()
    data = json_load(STORE, {"entries": [], "budgets": {}, "currency": ""})
    data.setdefault("entries", [])
    data.setdefault("budgets", {})
    cur = str(p.get("currency") or data.get("currency") or cfg().get("currency") or "USD").upper()
    try:
        if action in ("add", "expense", "spend", "spent", "income", "earn"):
            amount = float(p.get("amount"))
            if amount <= 0:
                return "The amount must be more than zero, sir."
            typ = "income" if action in ("income", "earn") or str(p.get("type") or "").lower() == "income" else "expense"
            note = str(p.get("note") or p.get("description") or "").strip()
            cat = str(p.get("category") or "").strip().title() or (_guess(note) if typ == "expense" else "Income")
            d = str(p.get("date") or "").strip().lower()
            d = date.today().isoformat() if d in ("", "today") else (date.fromordinal(date.today().toordinal() - 1).isoformat() if d == "yesterday" else datetime.strptime(d, "%Y-%m-%d").date().isoformat())
            data["entries"].append({"id": uuid.uuid4().hex[:8], "date": d, "type": typ, "amount": amount, "category": cat, "note": note})
            if p.get("currency"):
                data["currency"] = cur
            json_save(STORE, data)
            msg = f"Recorded {typ}: {_money(amount, cur)}" + (f" for {cat}" if typ == "expense" else "") + "."
            if typ == "expense":
                month = d[:7]
                spent = sum(e["amount"] for e in data["entries"] if e["type"] == "expense" and e["category"] == cat and e["date"].startswith(month))
                b = data["budgets"].get(cat)
                if b and spent > b:
                    msg += f" ⚠ {cat} is over its {_money(b, cur)} budget ({_money(spent, cur)} spent)."
                elif b and spent > 0.85 * b:
                    msg += f" Careful: {round(spent / b * 100)}% of the {cat} budget is used."
            return msg
        if action in ("summary", "report", "status", "month"):
            ents, text, total, inc = _summary(data, _month(p.get("month")), cur)
            if not ents:
                return "No transactions recorded for that month, sir."
            if player is not None and hasattr(player, "show_content"):
                player.show_content("FINANCES", text)
            return text
        if action in ("list", "recent"):
            rows = sorted(data["entries"], key=lambda e: e["date"], reverse=True)[: int(p.get("count") or 8)]
            if not rows:
                return "No transactions yet, sir."
            return "\n".join(f"{e['date']}  {'+' if e['type'] == 'income' else '−'}{_money(e['amount'], cur)}  {e['category']}  {e['note']}".rstrip() for e in rows)
        if action == "budget":
            cat = str(p.get("category") or "").strip().title()
            if not cat or p.get("amount") is None:
                return "Sir, tell me the category and the monthly limit."
            data["budgets"][cat] = float(p["amount"])
            json_save(STORE, data)
            return f"Monthly budget for {cat}: {_money(float(p['amount']), cur)}."
        if action in ("remove", "delete", "undo"):
            if not data["entries"]:
                return "Nothing to remove, sir."
            e = data["entries"].pop()
            json_save(STORE, data)
            return f"Removed the last entry: {_money(e['amount'], cur)} {e['category']}."
        if action in ("export", "excel", "xlsx"):
            from actions import _impl_office as ob
            month = _month(p.get("month"))
            ents, _, total, inc = _summary(data, month, cur)
            if not ents:
                return "No transactions for that month to export, sir."
            rows = [[e["date"], e["type"].title(), e["category"], e["note"], e["amount"]] for e in sorted(ents, key=lambda e: e["date"])]
            cats = sorted({e["category"] for e in ents if e["type"] == "expense"})
            spec = {"theme": "green", "sheets": [
                {"name": "Transactions", "title": f"Transactions {month}", "columns": [{"header": "Date"}, {"header": "Type"}, {"header": "Category"}, {"header": "Note", "width": 34}, {"header": f"Amount ({cur})", "format": "number"}],
                 "rows": rows, "totals": {"label": "Total", "label_column": 4, "columns": {"E": "sum"}}},
                {"name": "Summary", "title": f"Spending by category — {month}", "columns": [{"header": "Category"}, {"header": f"Spent ({cur})", "format": "number"}, {"header": "Share", "format": "percent"}],
                 "rows": [[c, f"=SUMIFS(Transactions!E:E,Transactions!C:C,A{{row}},Transactions!B:B,\"Expense\")", f"=B{{row}}/{max(total, 0.0001)}"] for c in cats],
                 "totals": {"label": "Total", "columns": {"B": "sum"}},
                 "charts": [{"type": "pie", "title": "Spending by category", "data_cols": ["B"], "cat_col": "A"}]}]}
            path = unique_path(output_dir("Spreadsheets"), safe_name(f"finances_{month}"), ".xlsx")
            ob.build_workbook(spec, path)
            open_path(path)
            log(f"[Finance] Exported {path}", player)
            return f"Exported {len(ents)} transactions to Excel with a category summary and chart: {path}"
    except (TypeError, ValueError) as e:
        return f"That didn't look right, sir: {e}"
    return "Unknown action. Available: add, summary, list, budget, remove, export."


TOOL = {
    "name": "finance_tracker",
    "description": (
        "Personal finance tracker. Records expenses and income (category guessed from the note), shows monthly "
        "summaries by category, sets monthly budgets per category with over-budget warnings, lists recent "
        "transactions, and exports a month to Excel with a chart. Use for 'I spent 50 on lunch', 'how much did I "
        "spend this month', 'set a food budget'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "add | income | summary | list | budget | remove | export"},
            "amount": {"type": "NUMBER", "description": "Amount of money"},
            "category": {"type": "STRING", "description": "Food, Transport, Bills, Shopping, Health, Fun, Education, Other"},
            "note": {"type": "STRING", "description": "What it was for"},
            "type": {"type": "STRING", "description": "expense (default) | income"},
            "date": {"type": "STRING", "description": "today | yesterday | YYYY-MM-DD"},
            "month": {"type": "STRING", "description": "this month | last month | YYYY-MM"},
            "currency": {"type": "STRING", "description": "Currency code, e.g. USD, UZS"},
            "count": {"type": "INTEGER", "description": "How many recent items to list"},
        },
    },
    "handler": finance_tracker,
}

# by ASDcuber521
