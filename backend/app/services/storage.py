"""Where files live, and signed links to them.

Files are stored as files_dir/<user id>/<sha256>.<ext>. The app shows previews and opens
documents through /f/<user>/<name>?sig=..., an HMAC-signed link, so a plain image URL or a
browser tab works without a login header and nobody can guess other people's files.
"""

import hashlib
import hmac
from pathlib import Path

from ..config import get_settings


def root() -> Path:
    r = Path(get_settings().files_dir)
    r.mkdir(parents=True, exist_ok=True)
    return r


def path_for(user_id: int, name: str) -> Path:
    return root() / str(user_id) / name


def save(user_id: int, name: str, data: bytes) -> Path:
    p = path_for(user_id, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(data)
    return p


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign(user_id: int, name: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"{user_id}/{name}".encode(), hashlib.sha256).hexdigest()[:32]


def verify(user_id: int, name: str, sig: str) -> bool:
    return hmac.compare_digest(sign(user_id, name), sig or "")


def signed_url(user_id: int, name: str | None) -> str | None:
    return f"/f/{user_id}/{name}?sig={sign(user_id, name)}" if name else None
