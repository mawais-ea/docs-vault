from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Category, Document, User
from ..schemas import CategoryIn, CategoryOut, CategoryPatch, ReorderIn
from ..services.classifier import OTHER

router = APIRouter(tags=["categories"])


def _owned(db: Session, user: User, category_id: int) -> Category:
    cat = db.get(Category, category_id)
    if not cat or cat.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return cat


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(Document.category_id, func.count())
        .where(Document.user_id == user.id, Document.deleted_at.is_(None))
        .group_by(Document.category_id)
    ).all())
    out = []
    for c in db.scalars(select(Category).where(Category.user_id == user.id).order_by(Category.sort_order, Category.id)):
        item = CategoryOut.model_validate(c)
        item.count = counts.get(c.id, 0)
        out.append(item)
    return out


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.scalar(select(Category).where(Category.user_id == user.id, Category.name == body.name.strip())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with that name already exists")
    order = (db.scalar(select(func.max(Category.sort_order)).where(Category.user_id == user.id)) or 0) + 1
    cat = Category(user_id=user.id, name=body.name.strip(), icon=body.icon, color=body.color, sort_order=order)
    db.add(cat)
    db.commit()
    return CategoryOut.model_validate(cat)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, body: CategoryPatch, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    cat = _owned(db, user, category_id)
    data = body.model_dump(exclude_unset=True)
    if cat.name == OTHER and data.get("name", OTHER) != OTHER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'"{OTHER}" cannot be renamed')
    for k, v in data.items():
        setattr(cat, k, v)
    db.commit()
    return CategoryOut.model_validate(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cat = _owned(db, user, category_id)
    if cat.name == OTHER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'"{OTHER}" cannot be deleted')
    other = db.scalar(select(Category).where(Category.user_id == user.id, Category.name == OTHER))
    db.execute(update(Document).where(Document.category_id == cat.id).values(category_id=other.id if other else None))
    db.delete(cat)
    db.commit()


@router.post("/categories/reorder", response_model=list[CategoryOut])
def reorder_categories(body: ReorderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user.id))}
    if any(i not in cats for i in body.ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    rest = sorted((c for i, c in cats.items() if i not in set(body.ids)), key=lambda c: c.sort_order)
    for order, cat in enumerate([cats[i] for i in body.ids] + rest):
        cat.sort_order = order
    db.commit()
    return list_categories(user, db)
