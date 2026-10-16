import pytest

from app.services import classifier, reader
from app.services.classifier import (
    DEFAULT_CATEGORIES, classify_by_rules, find_amount, find_date, find_issuer, suggested_file_name,
)
from tests.conftest import BILL, photo_jpeg, scanned_pdf, text_pdf

CATS = [c[0] for c in DEFAULT_CATEGORIES]


def test_text_pdf_is_read_without_ocr():
    r = reader.read(text_pdf(BILL))
    assert r.kind == "pdf" and r.pages == 1 and r.text_source == "pdf"
    assert "Amount due" in r.text and r.preview_jpeg[:2] == b"\xff\xd8"


def test_scanned_pdf_is_read_with_ocr():
    r = reader.read(scanned_pdf(["Electricity bill", "Account 12345678", "Amount due 84.20"]))
    assert r.text_source == "ocr" and "Electricity" in r.text and "12345678" in r.text


def test_photo_of_a_document_is_read_with_ocr():
    r = reader.read(photo_jpeg(["TESCO", "Receipt", "Total 12.50"]))
    assert r.kind == "image" and r.text_source == "ocr" and "Receipt" in r.text


def test_other_files_are_refused():
    with pytest.raises(reader.NotADocument):
        reader.detect(b"just some text, not a document")
    with pytest.raises(reader.NotADocument, match="HEIC"):
        reader.detect(bytes(3) + bytes([24]) + b"ftypheic" + bytes(32))


@pytest.mark.parametrize("text, expected", [
    ("Bill date: 03/10/2026", "2026-10-03"),
    ("Statement date 2026-09-30", "2026-09-30"),
    ("Issued on 3rd November 2026", "2026-11-03"),
    ("Dated Nov 3, 2026", "2026-11-03"),
    ("Valid until 12/31/2027", "2027-12-31"),  # clearly month-first
    ("No date here", None),
])
def test_find_date(text, expected):
    assert find_date(text) == expected


def test_labelled_date_beats_earlier_dates():
    assert find_date("Customer since 01/02/2015\nInvoice date: 05/10/2026") == "2026-10-05"


def test_find_amount_prefers_the_total():
    assert find_amount("Item £2.00\nVAT £0.40\nTotal £12.50") == "£12.50"
    assert find_amount("Net pay: GBP 2,345.67") == "£2,345.67"
    assert find_amount("nothing to pay") is None
    assert find_amount("Opening balance £1,200.00\nClosing balance £2,345.67") == "£2,345.67"
    assert find_amount("Subtotal £10.00\nTotal £12.50") == "£12.50"
    assert find_amount("Milk 1.20\nTotal f12.50") == "12.50"  # OCR misread the £


def test_find_issuer_skips_generic_lines():
    assert find_issuer("INVOICE\nAcme Plumbing Ltd\n12 High St") == "Acme Plumbing Ltd"


@pytest.mark.parametrize("lines, category", [
    (BILL, "Bills & Utilities"),
    (["HSBC UK", "Bank statement", "Sort code 40-11-22", "Opening balance £100", "Closing balance £250",
      "Statement period 1 Sep - 30 Sep 2026"], "Bank & Finance"),
    (["Emirates", "Boarding pass", "Flight EK623", "Departure Lahore", "Gate 12 Seat 34A"], "ID & Travel"),
    (["Aviva", "Certificate of insurance", "Policy number 123", "Premium £300", "Policyholder Mr A"], "Insurance"),
    (["Acme Ltd", "Payslip", "Pay period September", "Gross pay £3000", "Net pay £2400", "Employer Acme"],
     "Work & Payslips"),
])
def test_rules_pick_the_category(lines, category):
    c = classify_by_rules("\n".join(lines), CATS)
    assert c.category == category, c


def test_unclear_documents_fall_back_to_other():
    c = classify_by_rules("Hello\nsee you soon", CATS)
    assert c.category == "Other" and c.source == "fallback"


def test_suggested_file_name():
    c = classify_by_rules("\n".join(BILL), CATS)
    assert suggested_file_name(c, "pdf") == "2026-10-03 British Gas Bill.pdf"
    c.issuer = 'A/B "Bad" Name'
    assert "/" not in suggested_file_name(c, "pdf") and '"' not in suggested_file_name(c, "pdf")


async def test_claude_fills_in_and_rules_back_it_up(monkeypatch):
    import json

    seen = {}

    class Client:
        class messages:
            @staticmethod
            async def create(**kw):
                seen["content"] = kw["messages"][0]["content"]
                payload = {"category": "Bills & Utilities", "confidence": 0.9, "document_type": "Electricity bill",
                           "title": "British Gas electricity bill – Oct 2026", "issuer": "British Gas",
                           "doc_date": "", "amount": "£84.20", "description": "October electricity bill.",
                           "summary": "Electricity bill.\n- Due 17 Oct", "tags": ["energy"],
                           "suggested_new_category": ""}
                return type("M", (), {"stop_reason": "end_turn",
                                      "content": [type("B", (), {"type": "text", "text": json.dumps(payload)})()]})
    monkeypatch.setattr(classifier.get_settings(), "llm_enabled", True)
    monkeypatch.setattr(classifier.get_settings(), "anthropic_api_key", "test")
    monkeypatch.setattr(classifier, "_llm", lambda: Client)
    c = await classifier.classify("\n".join(BILL), CATS, [], "scan_001.pdf")
    assert c.source == "llm" and c.title.startswith("British Gas") and c.summary.startswith("Electricity")
    assert c.doc_date == "2026-10-03"  # Claude left it empty; the rules found it
    assert seen["content"][-1]["type"] == "text" and "Document text:" in seen["content"][-1]["text"]

    # A scan with no text: Claude gets the PDF itself.
    await classifier.classify("", CATS, [], "scan.pdf", file_bytes=b"%PDF-1.4 fake", mime="application/pdf")
    assert seen["content"][0]["type"] == "document"
