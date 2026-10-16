import os
import tempfile

# Throwaway database and files, no network, before anything imports the app.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["FILES_DIR"] = f"{_tmp}/files"
os.environ["LLM_ENABLED"] = "false"
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"

import io  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        r = c.post("/auth/register", json={"email": "me@example.com", "password": "correct-horse"})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        c.api_key = r.json()["api_key"]
        yield c


# ---------------------------------------------------------------- sample documents

def text_pdf(lines: list[str]) -> bytes:
    """A real one-page PDF with selectable text (what most bills/statements are)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 12 Tf 50 780 Td 16 TL " + " ".join(f"({esc(line)}) '" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def page_image(lines: list[str], size=(1240, 1754)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).multiline_text((80, 100), "\n".join(lines), fill="black",
                                       font=ImageFont.load_default(size=46), spacing=26)
    return img


def scanned_pdf(lines: list[str]) -> bytes:
    """A PDF that is just a picture of a page (no text layer), like a scan."""
    buf = io.BytesIO()
    page_image(lines).save(buf, "PDF", resolution=150)
    return buf.getvalue()


def photo_jpeg(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    page_image(lines, size=(1200, 900)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


BILL = ["British Gas", "Electricity bill", "Bill date: 03/10/2026", "Account number 8500 1234",
        "Energy used: 312 kWh", "Standing charge 0.53 per day", "Amount due: £84.20",
        "Paid by direct debit on 17 October 2026"]
