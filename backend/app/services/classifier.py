"""Work out what a document is: category, title, date, who it's from, amount, summary.

Without Claude: keyword rules pick the category and simple patterns find the date, amount and
sender. With Claude (ANTHROPIC_API_KEY): it reads the text, or the PDF/photo itself when the
text is thin (scans), and fills everything in, following the person's past corrections.
"""

import base64
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import anthropic

from ..config import get_settings

log = logging.getLogger(__name__)

OTHER = "Other"

# name, icon, color, keywords (phrases count more than words)
CATEGORIES: list[tuple[str, str, str, list[str]]] = [
    ("Bills & Utilities", "receipt_long", "#E64A19",
     ["electricity", "gas bill", "water bill", "broadband", "internet bill", "phone bill", "mobile bill",
      "utility", "meter reading", "energy", "tariff", "amount due", "your bill", "bill date", "direct debit",
      "council tax", "standing charge", "kwh", "units used"]),
    ("Bank & Finance", "account_balance", "#2E7D32",
     ["bank statement", "account statement", "sort code", "iban", "swift", "balance brought forward",
      "transactions", "credit card statement", "statement period", "opening balance", "closing balance",
      "loan", "interest rate", "investment", "pension", "account number", "overdraft", "savings"]),
    ("Insurance", "shield", "#1565C0",
     ["insurance", "policy number", "policyholder", "premium", "insured", "cover", "excess", "claim",
      "certificate of insurance", "schedule of insurance", "renewal"]),
    ("Tax", "request_quote", "#6A1B9A",
     ["tax return", "hmrc", "irs", "p60", "p45", "self assessment", "tax year", "vat return", "fbr",
      "withholding tax", "tax code", "national insurance", "taxable", "w-2", "1099"]),
    ("Receipts & Purchases", "shopping_bag", "#F57C00",
     ["receipt", "order number", "order confirmation", "thank you for your order", "subtotal", "invoice",
      "purchase", "qty", "quantity", "delivery", "dispatched", "vat receipt", "paid with", "card ending"]),
    ("Work & Payslips", "work", "#3949AB",
     ["payslip", "pay slip", "salary", "net pay", "gross pay", "employer", "employee", "employment",
      "offer letter", "contract of employment", "p11d", "pay period", "deductions", "timesheet"]),
    ("ID & Travel", "flight", "#0097A7",
     ["passport", "visa", "boarding pass", "e-ticket", "itinerary", "flight", "booking confirmation",
      "hotel", "check-in", "driving licence", "driver's license", "identity card", "residence permit", "brp",
      "cnic", "booking reference", "departure", "arrival", "gate", "seat"]),
    ("Health & Medical", "medical_services", "#C62828",
     ["prescription", "patient", "nhs", "hospital", "clinic", "appointment", "diagnosis", "test results",
      "vaccination", "gp", "doctor", "pharmacy", "medication", "dosage", "blood", "referral", "dental"]),
    ("Home & Property", "home", "#8D6E63",
     ["tenancy agreement", "lease", "rent", "landlord", "tenant", "mortgage", "property", "deposit",
      "estate agent", "inventory", "freehold", "leasehold", "completion"]),
    ("Education & Certificates", "school", "#5E35B1",
     ["certificate", "transcript", "diploma", "degree", "university", "school", "course", "enrolment",
      "enrollment", "grades", "graduation", "student", "certification", "awarded"]),
    ("Car & Vehicle", "directions_car", "#455A64",
     ["vehicle", "mot", "v5c", "registration number", "service history", "dvla", "parking", "penalty charge",
      "mileage", "car insurance", "road tax", "vin"]),
    ("Manuals & Warranty", "menu_book", "#00897B",
     ["user manual", "instructions", "warranty", "guarantee", "quick start", "safety information",
      "specifications", "model number", "troubleshooting", "installation"]),
    ("Letters & Government", "mail", "#607D8B",
     ["dear", "yours sincerely", "yours faithfully", "council", "government", "ministry", "department",
      "court", "embassy", "home office", "notice", "reference number"]),
    (OTHER, "folder", "#78909C", []),
]
DEFAULT_CATEGORIES = [(n, i, c) for n, i, c, _ in CATEGORIES]
KEYWORDS = {n: k for n, _, _, k in CATEGORIES}

# Document types worth naming in titles/file names, most specific first.
DOC_TYPES = [
    ("bank statement", "Bank statement"), ("credit card statement", "Credit card statement"),
    ("account statement", "Statement"), ("tax return", "Tax return"), ("payslip", "Payslip"),
    ("pay slip", "Payslip"), ("boarding pass", "Boarding pass"), ("e-ticket", "E-ticket"),
    ("booking confirmation", "Booking confirmation"), ("certificate of insurance", "Insurance certificate"),
    ("insurance", "Insurance"), ("prescription", "Prescription"), ("tenancy agreement", "Tenancy agreement"),
    ("invoice", "Invoice"), ("receipt", "Receipt"), ("order confirmation", "Order confirmation"),
    ("user manual", "Manual"), ("warranty", "Warranty"), ("certificate", "Certificate"),
    ("transcript", "Transcript"), ("passport", "Passport"), ("visa", "Visa"), ("contract", "Contract"),
    ("bill", "Bill"), ("statement", "Statement"), ("letter", "Letter"),
]


@dataclass
class Classification:
    category: str = OTHER
    confidence: float = 0.0
    source: str = "rules"  # rules | llm | fallback
    title: str | None = None
    description: str | None = None
    summary: str | None = None
    doc_date: str | None = None
    issuer: str | None = None
    amount: str | None = None
    doc_type: str | None = None
    tags: list[str] = field(default_factory=list)
    suggested_new_category: str | None = None


# ---------------------------------------------------------------- rules

def _count(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text))


def rule_category(text: str, categories: list[str]) -> tuple[str | None, float]:
    """Keyword scores; the start of a document (its heading) counts double."""
    low = text.lower()
    head = low[:1500]
    scores: Counter[str] = Counter()
    for cat, keywords in KEYWORDS.items():
        if cat not in categories:
            continue
        for kw in keywords:
            n = min(_count(low, kw), 3) + min(_count(head, kw), 2)
            if n:
                scores[cat] += n * (2 if " " in kw else 1)
    if not scores:
        return None, 0.0
    (top, top_score), *rest = scores.most_common(2) + [("", 0)]
    second = rest[0][1]
    if top_score >= 3 and top_score >= 1.5 * second:
        return top, min(0.55 + 0.04 * top_score, 0.85)
    return None, 0.0


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (re.compile(r"\b(20\d\d|19\d\d)-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](20\d\d|19\d\d)\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d|19\d\d)\b", re.I), "d_mon_y"),
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d|19\d\d)\b", re.I), "mon_d_y"),
]
_DATE_LABEL = re.compile(r"(date|dated|issued|statement|invoice date|bill date|period|on)\b", re.I)


def find_date(text: str) -> str | None:
    """The document's own date: one next to a 'Date'-style label first, else the earliest one mentioned."""
    found: list[tuple[int, bool, str]] = []
    for line_no, line in enumerate(text[:6000].splitlines()):
        for pattern, kind in _DATE_PATTERNS:
            for m in pattern.finditer(line):
                g = m.groups()
                try:
                    if kind == "ymd":
                        y, mo, d = int(g[0]), int(g[1]), int(g[2])
                    elif kind == "dmy":
                        d, mo, y = int(g[0]), int(g[1]), int(g[2])
                        if mo > 12 and d <= 12:  # clearly month-first (US style)
                            d, mo = mo, d
                    elif kind == "d_mon_y":
                        d, mo, y = int(g[0]), MONTHS[g[1][:3].lower()], int(g[2])
                    else:
                        mo, d, y = MONTHS[g[0][:3].lower()], int(g[1]), int(g[2])
                    iso = date(y, mo, d).isoformat()
                except (ValueError, KeyError):
                    continue
                found.append((line_no, bool(_DATE_LABEL.search(line)), iso))
    if not found:
        return None
    labelled = [f for f in found if f[1]]
    return (labelled or found)[0][2]


_AMOUNT = re.compile(r"(£|\$|€|₨|rs\.?|pkr|gbp|usd|eur|aed)\s?(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)", re.I)
_TOTAL_LABEL = re.compile(r"(total|amount due|balance due|to pay|amount payable|grand total|net pay|premium|"
                          r"closing balance)", re.I)
_MONEY_NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![\d.])")


def find_amount(text: str) -> str | None:
    """The main amount: on a 'Total / Amount due / Closing balance…' line if there is one."""
    best = labelled = None
    for line in text[:8000].splitlines():
        m = _AMOUNT.search(line)
        is_total = bool(_TOTAL_LABEL.search(line))
        if m:
            sym = m.group(1)
            sym = {"gbp": "£", "usd": "$", "eur": "€"}.get(sym.lower(), sym.upper() if sym.isalpha() else sym)
            value = sym + ("" if len(sym) == 1 else " ") + m.group(2).replace(" ", "")
            if is_total:
                labelled = value  # the last total wins: "Subtotal" comes before "Total"
            best = best or value
        elif is_total and (n := _MONEY_NUMBER.findall(line)):
            labelled = n[-1]  # scans often misread "£" (as "f", "E"…): keep the number
    return labelled or best


_GENERIC_LINE = re.compile(r"^(page \d|invoice|statement|receipt|date|tax invoice|bill|to:|from:|www\.|http|tel|phone|email|dear)", re.I)


def find_issuer(text: str) -> str | None:
    """Usually the first real line of a document is who it's from (letterhead/logo text)."""
    for line in text.splitlines()[:15]:
        line = " ".join(line.split()).strip(" -|:•")
        letters = sum(c.isalpha() for c in line)
        if 3 <= letters and len(line) <= 50 and not _GENERIC_LINE.match(line) and not any(ch.isdigit() for ch in line[:3]):
            return line
    return None


def find_doc_type(text: str) -> str | None:
    head = text[:3000].lower()
    for phrase, label in DOC_TYPES:
        if _count(head, phrase):
            return label
    return None


def first_sentences(text: str, limit: int = 160) -> str | None:
    text = " ".join(text.split())
    if not text:
        return None
    cut = text[:limit]
    return cut if len(text) <= limit else cut.rsplit(" ", 1)[0] + "…"


# A heading that says what the document is ("RECEIPT", "Bank statement") settles short documents.
DOC_TYPE_CATEGORY = {
    "Bank statement": "Bank & Finance", "Credit card statement": "Bank & Finance", "Statement": "Bank & Finance",
    "Tax return": "Tax", "Payslip": "Work & Payslips", "Boarding pass": "ID & Travel", "E-ticket": "ID & Travel",
    "Booking confirmation": "ID & Travel", "Passport": "ID & Travel", "Visa": "ID & Travel",
    "Insurance certificate": "Insurance", "Insurance": "Insurance", "Prescription": "Health & Medical",
    "Tenancy agreement": "Home & Property", "Invoice": "Receipts & Purchases", "Receipt": "Receipts & Purchases",
    "Order confirmation": "Receipts & Purchases", "Manual": "Manuals & Warranty", "Warranty": "Manuals & Warranty",
    "Certificate": "Education & Certificates", "Transcript": "Education & Certificates", "Bill": "Bills & Utilities",
}


def heading_type(text: str) -> str | None:
    """The document type if one of the first few lines names it."""
    head = "\n".join(text.splitlines()[:5]).lower()
    for phrase, label in DOC_TYPES:
        if _count(head, phrase):
            return label
    return None


def classify_by_rules(text: str, categories: list[str], original_name: str | None = None) -> Classification:
    cat, conf = rule_category((original_name or "") + "\n" + text, categories)
    if not cat and (label := heading_type(text)) and DOC_TYPE_CATEGORY.get(label) in categories:
        cat, conf = DOC_TYPE_CATEGORY[label], 0.6
    c = Classification(category=cat or OTHER, confidence=conf, source="rules" if cat else "fallback")
    c.doc_date = find_date(text)
    c.amount = find_amount(text)
    c.issuer = find_issuer(text)
    c.doc_type = find_doc_type(text)
    label = c.doc_type or (cat or "Document").split(" & ")[0].rstrip("s")
    if c.issuer:
        c.title = f"{label} – {c.issuer}"
    elif original_name and not re.match(r"^(scan|img|image|document|doc|file|pdf)?[_\- ]?\d*\.", original_name, re.I):
        c.title = re.sub(r"\.[a-z0-9]{2,4}$", "", original_name, flags=re.I)
    else:
        c.title = label
    c.description = first_sentences(text)
    return c


# ---------------------------------------------------------------- Claude

_client: anthropic.AsyncAnthropic | None = None


def _llm() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key or None, max_retries=3, timeout=120.0)
    return _client


def _schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories},
            "confidence": {"type": "number"},
            "document_type": {"type": "string"},
            "title": {"type": "string"},
            "issuer": {"type": "string"},
            "doc_date": {"type": "string"},
            "amount": {"type": "string"},
            "description": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "suggested_new_category": {"type": "string"},
        },
        "required": ["category", "confidence", "document_type", "title", "issuer", "doc_date", "amount",
                     "description", "summary", "tags", "suggested_new_category"],
        "additionalProperties": False,
    }


def _instructions(categories: list[str], examples: list[str], original_name: str | None) -> str:
    lang = get_settings().summary_language
    return f"""This is a document someone saved to their personal document vault. Read it and file it.

Their categories: {", ".join(categories)}
Their past corrections (follow these preferences): {"; ".join(examples) if examples else "none"}
Original file name: {original_name or "unknown"}

Return:
- category: the best fit from the list; "{OTHER}" only if nothing fits.
- confidence: 0 to 1.
- document_type: what it is in 1-3 words (e.g. "Electricity bill", "Bank statement", "Boarding pass").
- title: short and specific, e.g. "British Gas electricity bill – Oct 2026" (under 70 characters).
- issuer: the company, person or organisation it is from, or "".
- doc_date: the document's own date (issue/statement/bill date) as YYYY-MM-DD, or "".
- amount: the main amount with currency if there is one (total, amount due, net pay, premium), e.g. "£84.20", or "".
- description: one sentence (under 160 characters) saying what it is and why it matters.
- summary: the key details so they rarely need to open it: one sentence, then bullet lines ("- ") with
  dates, deadlines, amounts, reference/account/policy numbers, names and anything they must act on.
  Only what is in the document; never invent details.
- tags: up to 4 short lowercase tags.
- suggested_new_category: if no category fits well and a short new one would (e.g. "Pets"), else "".
Write title, document_type, description, summary and tags in {lang} (translate if needed)."""


async def classify_with_claude(text: str, categories: list[str], examples: list[str], original_name: str | None,
                               file_bytes: bytes | None = None, mime: str | None = None) -> Classification | None:
    """Text-first (cheap). When the text is thin (scans, photos) and the file is small enough,
    Claude reads the PDF or image itself."""
    s = get_settings()
    if not s.llm_ready():
        return None
    content: list[dict] = []
    thin = len(text.strip()) < 200
    if thin and file_bytes and len(file_bytes) < 20_000_000:
        b64 = base64.b64encode(file_bytes).decode()
        if mime == "application/pdf":
            content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}})
        elif mime in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
    prompt = _instructions(categories, examples, original_name)
    if not content:
        prompt += f"\n\nDocument text:\n{text[:60000]}"
    content.append({"type": "text", "text": prompt})
    try:
        msg = await _llm().messages.create(
            model=s.llm_model, max_tokens=8000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema(categories)}},
            messages=[{"role": "user", "content": content}],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning("Claude couldn't read the document: %s", e)
        return None
    except TypeError as e:  # no credentials configured
        if "authentication" not in str(e).lower():
            raise
        return None
    if msg.stop_reason != "end_turn":
        log.warning("Claude stopped with %s", msg.stop_reason)
        return None
    try:
        d = json.loads(next((b.text for b in msg.content if b.type == "text"), ""))
    except json.JSONDecodeError:
        return None
    category = d.get("category") if d.get("category") in categories else OTHER
    doc_date = d.get("doc_date") or None
    if doc_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc_date):
        doc_date = None
    return Classification(
        category=category, confidence=float(d.get("confidence") or 0), source="llm",
        title=(d.get("title") or "").strip()[:200] or None, description=(d.get("description") or "").strip()[:300] or None,
        summary=(d.get("summary") or "").strip()[:8000] or None, doc_date=doc_date,
        issuer=(d.get("issuer") or "").strip()[:200] or None, amount=(d.get("amount") or "").strip()[:60] or None,
        doc_type=(d.get("document_type") or "").strip()[:60] or None,
        tags=[t.strip().lower() for t in d.get("tags") or [] if t.strip()][:4],
        suggested_new_category=(d.get("suggested_new_category") or "").strip()[:80] or None,
    )


async def classify(text: str, categories: list[str], examples: list[str], original_name: str | None = None,
                   file_bytes: bytes | None = None, mime: str | None = None) -> Classification:
    by_rules = classify_by_rules(text, categories, original_name)
    by_llm = await classify_with_claude(text, categories, examples, original_name, file_bytes, mime)
    if not by_llm:
        return by_rules
    if by_llm.confidence < get_settings().llm_min_confidence and by_rules.source == "rules":
        by_llm.category, by_llm.confidence = by_rules.category, by_rules.confidence
    # Fill anything Claude left empty from the rules.
    for f in ("doc_date", "amount", "issuer", "doc_type", "title", "description"):
        if not getattr(by_llm, f):
            setattr(by_llm, f, getattr(by_rules, f))
    return by_llm


# ---------------------------------------------------------------- naming

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def suggested_file_name(c: Classification, ext: str) -> str:
    """'2026-10-03 British Gas Electricity bill.pdf'"""
    parts = [c.doc_date or "", c.issuer or "", c.doc_type or (c.title if not c.issuer else "") or "Document"]
    name = " ".join(p for p in parts if p)
    name = _UNSAFE.sub(" ", name)
    name = " ".join(name.split())[:120].strip(" .")
    return f"{name or 'Document'}.{ext}"
