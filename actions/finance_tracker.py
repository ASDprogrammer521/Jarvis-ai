from __future__ import annotations

import mimetypes
import uuid
from datetime import date, datetime
from pathlib import Path

from actions._common import DATA_DIR, ask_json, cfg, json_load, json_save, log, open_path, output_dir, safe_name, unique_path

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


CATEGORIES = ("Food", "Transport", "Bills", "Shopping", "Health", "Fun", "Education", "Other")
RECEIPT_SYSTEM = (
    "You read photos of shop receipts, restaurant checks and bills (any language: Uzbek, Russian, English...). "
    "Reply with ONE JSON object and nothing else: "
    '{"is_receipt":bool,"total":number,"currency":str,"merchant":str,"category":str,"date":"YYYY-MM-DD"|null,"items":str}. '
    "total = the FINAL amount paid (JAMI / ITOGO / TOTAL / к оплате), not a subtotal, tax line or change. "
    "Write the number without spaces or thousand separators (e.g. 125000). "
    "currency = ISO code (UZS for so'm/сум, USD, EUR, RUB...) or null if unclear. "
    f"category must be one of: {', '.join(CATEGORIES)}. items = a few main purchased items, comma separated, max 80 chars. "
    "If the picture is not a receipt or the total is unreadable, set is_receipt=false and total=0."
)


def read_receipt(image_path: str) -> dict | None:
    """Ask Gemini to read a receipt photo. Returns the parsed dict or None."""
    p = Path(str(image_path)).expanduser()
    if not p.is_file():
        return None
    from google.genai import types
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    contents = [types.Part.from_bytes(data=p.read_bytes(), mime_type=mime), "Read this receipt."]
    res = ask_json(contents, RECEIPT_SYSTEM, default=None, timeout_ms=60_000)
    return res if isinstance(res, dict) else None


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
        if action in ("scan_receipt", "receipt", "scan", "photo"):
            img = str(p.get("image_path") or p.get("file_path") or "").strip()
            if not img:
                return "Sir, attach a photo of the receipt first (use the paperclip), then ask me again."
            if not Path(img).expanduser().is_file():
                return f"I can't find that image: {img}"
            r = read_receipt(img)
            if not r or not r.get("is_receipt", True):
                return "I couldn't read a receipt in that picture, sir. Try a sharper, well-lit photo of the whole receipt."
            try:
                amount = float(str(r.get("total")).replace(" ", "").replace(",", "."))
            except (TypeError, ValueError):
                amount = 0.0
            if amount <= 0:
                return "I could see the receipt but not the total amount. Please tell me the amount and I'll record it."
            note_cur = ""
            rc = str(r.get("currency") or "").upper().strip()
            if rc and not p.get("currency") and rc != cur:
                if not data.get("currency") and not cfg().get("currency"):
                    cur = rc
                    data["currency"] = rc
                else:
                    note_cur = f" (receipt currency: {rc})"
            merchant = str(r.get("merchant") or "").strip()
            items = str(r.get("items") or "").strip()
            note = " — ".join(x for x in (merchant, items) if x)[:120]
            cat = str(r.get("category") or "").strip().title()
            if cat not in CATEGORIES:
                cat = _guess(note)
            d = str(r.get("date") or "").strip()
            try:
                d = datetime.strptime(d, "%Y-%m-%d").date()
                d = d.isoformat() if d <= date.today() else date.today().isoformat()
            except ValueError:
                d = date.today().isoformat()
            data["entries"].append({"id": uuid.uuid4().hex[:8], "date": d, "type": "expense", "amount": amount,
                                    "category": cat, "note": note, "source": "receipt"})
            json_save(STORE, data)
            msg = f"Receipt recorded: {_money(amount, cur)} · {cat}" + (f" · {merchant}" if merchant else "") + f" · {d}.{note_cur}"
            spent = sum(e["amount"] for e in data["entries"] if e["type"] == "expense" and e["category"] == cat and e["date"].startswith(d[:7]))
            b = data["budgets"].get(cat)
            if b and spent > b:
                msg += f" ⚠ {cat} is over its {_money(b, cur)} budget ({_money(spent, cur)} spent)."
            msg += " If that's wrong, say 'remove the last entry'."
            log(f"[Finance] {msg}", player)
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
            from actions import office_builder as ob
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
    return "Unknown action. Available: add, scan_receipt, summary, list, budget, remove, export."


TOOL = {
    "name": "finance_tracker",
    "description": (
        "Personal finance tracker. Records expenses and income (category guessed from the note), shows monthly "
        "summaries by category, sets monthly budgets per category with over-budget warnings, lists recent "
        "transactions, and exports a month to Excel with a chart. Use for 'I spent 50 on lunch', 'how much did I "
        "spend this month', 'set a food budget'. When the user shows/attaches a photo of a receipt or bill "
        "('chekni yoz', 'record this receipt'), call with action=scan_receipt: the image is read and the expense is saved."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "add | income | scan_receipt | summary | list | budget | remove | export"},
            "amount": {"type": "NUMBER", "description": "Amount of money"},
            "category": {"type": "STRING", "description": "Food, Transport, Bills, Shopping, Health, Fun, Education, Other"},
            "note": {"type": "STRING", "description": "What it was for"},
            "type": {"type": "STRING", "description": "expense (default) | income"},
            "date": {"type": "STRING", "description": "today | yesterday | YYYY-MM-DD"},
            "month": {"type": "STRING", "description": "this month | last month | YYYY-MM"},
            "currency": {"type": "STRING", "description": "Currency code, e.g. USD, UZS"},
            "image_path": {"type": "STRING", "description": "Receipt photo path for scan_receipt (defaults to the file attached in the UI)"},
            "count": {"type": "INTEGER", "description": "How many recent items to list"},
        },
    },
    "handler": finance_tracker,
}

# by ASDcuber521
