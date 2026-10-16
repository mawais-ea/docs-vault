from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Category, Correction, Document, User, utcnow
from ..schemas import DocumentList, DocumentOut, DocumentPatch
from ..services import storage
from ..services.pipeline import process_document, save_upload

router = APIRouter(tags=["documents"])


def to_out(doc: Document, with_text: bool = False, already_saved: bool = False) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.category_name = doc.category.name if doc.category else None
    out.tags = list(doc.tags or [])
    out.text = doc.text if with_text else None
    out.file_url = storage.signed_url(doc.user_id, doc.file_name)
    out.download_url = out.file_url + "&download=1"
    out.thumb_url = storage.signed_url(doc.user_id, doc.thumb_name)
    out.already_saved = already_saved
    return out


def _owned(db: Session, user: User, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id or doc.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


# ---------------------------------------------------------------- adding

@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(tasks: BackgroundTasks, file: UploadFile = File(...), note: str | None = Form(None),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read()
    doc, already = save_upload(db, user, data, file.filename, note)
    if not already:
        tasks.add_task(process_document, doc.id)
    return to_out(doc, already_saved=already)


@router.post("/u/{key}", response_class=PlainTextResponse)
async def upload_with_key(key: str, request: Request, tasks: BackgroundTasks, name: str | None = None,
                          db: Session = Depends(get_db)):
    """iPhone Shortcut: POST the file as the request body (Request Body: File) to /u/<api key>.
    No headers or form fields needed; a multipart form with a file works too. ?name= is optional."""
    user = db.scalar(select(User).where(User.api_key == key)) if key else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong API key")
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        files = [v for v in form.values() if hasattr(v, "read")]
        data = await files[0].read() if files else b""
        name = name or (getattr(files[0], "filename", None) if files else None)
    else:
        data = await request.body()
    doc, already = save_upload(db, user, data, name)
    if not already:
        tasks.add_task(process_document, doc.id)
        return PlainTextResponse("Saved ✓ " + (doc.title or "document"))
    return PlainTextResponse("Already saved ✓ " + (doc.title or "document"))


# ---------------------------------------------------------------- browsing

@router.get("/documents", response_model=DocumentList)
def list_documents(
    category: str | None = Query(None, description="Category id or name"),
    q: str | None = Query(None, description="Search titles, senders, summaries and the full text"),
    review: bool | None = None,
    favorite: bool | None = None,
    duplicates: bool | None = Query(None, description="Only documents that look like a copy of another"),
    limit: int = Query(200, le=1000),
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Document).where(Document.user_id == user.id, Document.deleted_at.is_(None))
    if category:
        if category.isdigit():
            stmt = stmt.where(Document.category_id == int(category))
        else:
            stmt = stmt.join(Category, Category.id == Document.category_id).where(Category.name == category)
    if review is not None:
        stmt = stmt.where(Document.needs_review.is_(review))
    if favorite is not None:
        stmt = stmt.where(Document.is_favorite.is_(favorite))
    if duplicates:
        stmt = stmt.where(Document.duplicate_of.is_not(None))
    for term in (q or "").split()[:8]:
        like = f"%{term}%"
        stmt = stmt.where(or_(
            Document.title.ilike(like), Document.description.ilike(like), Document.summary.ilike(like),
            Document.text.ilike(like), Document.issuer.ilike(like), Document.original_name.ilike(like),
            Document.note.ilike(like), Document.amount.ilike(like), Document.doc_date.ilike(like),
            cast(Document.tags, Text).ilike(like),
        ))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(stmt.order_by(Document.position.desc(), Document.id.desc()).limit(limit).offset(offset)).unique()
    return DocumentList(items=[to_out(d) for d in rows], total=total or 0)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return to_out(_owned(db, user, document_id), with_text=True)


# ---------------------------------------------------------------- changing

@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(document_id: int, body: DocumentPatch, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    doc = _owned(db, user, document_id)
    data = body.model_dump(exclude_unset=True)

    new_cat: Category | None = None
    if (name := data.pop("category", None)) is not None:
        name = name.strip()[:80]
        new_cat = db.scalar(select(Category).where(Category.user_id == user.id, Category.name == name))
        if not new_cat:  # accepting a suggested category creates it
            order = (db.scalar(select(func.max(Category.sort_order)).where(Category.user_id == user.id)) or 0) + 1
            new_cat = Category(user_id=user.id, name=name, sort_order=order)
            db.add(new_cat)
            db.flush()
    elif (cid := data.pop("category_id", None)) is not None:
        new_cat = db.get(Category, cid)
        if not new_cat or new_cat.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    data.pop("category_id", None)

    if new_cat and new_cat.id != doc.category_id:
        if doc.status != "processing" or doc.category_id is not None:
            db.add(Correction(user_id=user.id, document_id=doc.id, from_category_id=doc.category_id,
                              to_category_id=new_cat.id))
        doc.category_id = new_cat.id
        doc.needs_review = False
        if doc.suggested_category == new_cat.name:
            doc.suggested_category = None
    for key, value in data.items():
        setattr(doc, key, value)
    if data.get("needs_review") is False:
        doc.suggested_category = None
    db.commit()
    db.refresh(doc)
    return to_out(doc)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = _owned(db, user, document_id)
    doc.deleted_at = utcnow()
    db.commit()


@router.post("/documents/{document_id}/refresh", response_model=DocumentOut)
def refresh_document(document_id: int, tasks: BackgroundTasks, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Read and file it again (e.g. after adding a Claude API key)."""
    doc = _owned(db, user, document_id)
    doc.status = "processing"
    doc.category_id = None
    doc.suggested_category = None
    db.commit()
    tasks.add_task(process_document, doc.id)
    return to_out(doc)


# ---------------------------------------------------------------- files

@router.get("/f/{user_id}/{name}", include_in_schema=False)
def get_file(user_id: int, name: str, sig: str = Query(""), download: bool = False, db: Session = Depends(get_db)):
    if "/" in name or "\\" in name or ".." in name or not storage.verify(user_id, name, sig):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = storage.path_for(user_id, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    nice = None
    doc = db.scalar(select(Document).where(Document.user_id == user_id, Document.file_name == name))
    if doc:
        nice = doc.suggested_name or doc.original_name or name
    return FileResponse(
        path, filename=nice, content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
