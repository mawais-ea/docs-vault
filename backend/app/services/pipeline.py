"""Saving and processing documents.

save_upload() stores the file at once (the app shows it straight away as "Reading…");
process_document() then reads, classifies and summarises it in the background.
"""

import asyncio
import hashlib
import logging
import re
import time

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db as db_module
from ..config import get_settings
from ..models import Category, Correction, Document, User, utcnow
from . import classifier, reader, storage

log = logging.getLogger(__name__)


def seed_default_categories(db: Session, user: User) -> None:
    for i, (name, icon, color) in enumerate(classifier.DEFAULT_CATEGORIES):
        db.add(Category(user_id=user.id, name=name, icon=icon, color=color, sort_order=i, is_default=True))


def user_categories(db: Session, user_id: int) -> list[Category]:
    return list(db.scalars(select(Category).where(Category.user_id == user_id).order_by(Category.sort_order)))


def correction_examples(db: Session, user_id: int, limit: int = 10) -> list[str]:
    rows = db.execute(
        select(Document.title, Document.issuer, Category.name)
        .join(Correction, Correction.document_id == Document.id)
        .join(Category, Category.id == Correction.to_category_id)
        .where(Correction.user_id == user_id)
        .order_by(Correction.created_at.desc()).limit(limit)
    ).all()
    return [f'"{(t or "")[:60]}" from {i or "?"} -> {c}' for t, i, c in rows]


def save_upload(db: Session, user: User, data: bytes, original_name: str | None = None,
                note: str | None = None) -> tuple[Document, bool]:
    """Store the file and create its document. Returns (document, already_saved)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No file received")
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {get_settings().max_upload_mb} MB")
    try:
        kind, mime, ext = reader.detect(data)
    except reader.NotADocument as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    sha = storage.sha256(data)
    existing = db.scalar(select(Document).where(Document.user_id == user.id, Document.sha256 == sha))
    if existing:  # exactly the same file again: bring it back to the top instead of a copy
        if existing.deleted_at:
            existing.deleted_at = None
        existing.position = time.time()
        if note and not existing.note:
            existing.note = note
        db.commit()
        return existing, True

    name = f"{sha[:32]}.{ext}"
    storage.save(user.id, name, data)
    doc = Document(
        user_id=user.id, sha256=sha, file_name=name, original_name=(original_name or "")[:255] or None,
        kind=kind, mime=mime, size=len(data), note=note, status="processing", tags=[],
        title=_name_without_ext(original_name),
    )
    db.add(doc)
    db.commit()
    return doc, False


def _name_without_ext(name: str | None) -> str | None:
    return re.sub(r"\.[A-Za-z0-9]{2,4}$", "", name).strip() or None if name else None


def _text_hash(text: str) -> str | None:
    norm = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
    return hashlib.sha256(norm.encode()).hexdigest() if len(norm) >= 200 else None


async def process_document(document_id: int) -> None:
    db = db_module.SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc or doc.deleted_at:
            return
        try:
            await _process(db, doc)
        except Exception:
            log.exception("processing document %s failed", document_id)
            db.rollback()
            doc = db.get(Document, document_id)
            if doc:
                doc.status = "failed"
                if doc.category_id is None:
                    other = db.scalar(select(Category).where(Category.user_id == doc.user_id,
                                                             Category.name == classifier.OTHER))
                    doc.category_id = other.id if other else None
                db.commit()
    finally:
        db.close()


async def _process(db: Session, doc: Document) -> None:
    data = storage.path_for(doc.user_id, doc.file_name).read_bytes()
    result = await asyncio.to_thread(reader.read, data)

    if result.preview_jpeg:
        thumb = f"{doc.sha256[:32]}.preview.jpg"
        storage.save(doc.user_id, thumb, result.preview_jpeg)
        doc.thumb_name = thumb
    doc.pages = result.pages
    doc.text = result.text or None
    doc.text_source = result.text_source
    doc.text_hash = _text_hash(result.text)

    # Same content saved before as a different file (e.g. re-downloaded or re-scanned)?
    if doc.text_hash:
        twin = db.scalar(select(Document.id).where(
            Document.user_id == doc.user_id, Document.text_hash == doc.text_hash,
            Document.id != doc.id, Document.deleted_at.is_(None)).order_by(Document.id))
        doc.duplicate_of = twin

    cats = user_categories(db, doc.user_id)
    by_name = {c.name: c for c in cats}
    c = await classifier.classify(
        result.text, [x.name for x in cats] or [classifier.OTHER], correction_examples(db, doc.user_id),
        doc.original_name, file_bytes=data, mime=doc.mime,
    )

    doc.title = c.title or doc.title
    doc.description = c.description
    doc.doc_date = c.doc_date
    doc.issuer = c.issuer
    doc.amount = c.amount
    doc.tags = c.tags
    doc.confidence = c.confidence
    if c.summary:
        doc.summary, doc.summary_source = c.summary, "ai"
    else:
        doc.summary, doc.summary_source = _quick_summary(c), ("quick" if _quick_summary(c) else None)
    doc.suggested_name = classifier.suggested_file_name(c, "pdf" if doc.kind == "pdf" else doc.file_name.rsplit(".", 1)[-1])
    if doc.category_id is None:  # don't overrule a category picked while it was being read
        cat = by_name.get(c.category) or by_name.get(classifier.OTHER)
        doc.category_id = cat.id if cat else None
    if c.suggested_new_category and c.suggested_new_category not in by_name:
        doc.suggested_category = c.suggested_new_category
    doc.needs_review = c.source == "fallback" or (c.source == "llm" and (
        c.confidence < get_settings().llm_min_confidence or bool(doc.suggested_category)))
    doc.status = "ready"
    doc.updated_at = utcnow()
    db.commit()


def _quick_summary(c: classifier.Classification) -> str | None:
    """Without Claude: the facts the rules found, as a short list."""
    lines = [f"- {label}: {value}" for label, value in (
        ("From", c.issuer), ("Date", c.doc_date), ("Amount", c.amount), ("Type", c.doc_type)) if value]
    return "\n".join(lines) or None
