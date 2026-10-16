from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(RegisterIn):
    pass


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    api_key: str


class MeOut(BaseModel):
    id: int
    email: str
    api_key: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    icon: str = "folder"
    color: str = "#607D8B"


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = None
    color: str | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str
    color: str
    sort_order: int
    is_default: bool
    count: int = 0


class ReorderIn(BaseModel):
    ids: list[int] = Field(min_length=1)


class DocumentPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    note: str | None = None
    issuer: str | None = None
    doc_date: str | None = None
    amount: str | None = None
    category_id: int | None = None
    category: str | None = None  # by name: accepting a suggested new category creates it
    tags: list[str] | None = None
    is_favorite: bool | None = None
    needs_review: bool | None = None
    position: float | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    original_name: str | None
    suggested_name: str | None
    kind: str
    mime: str
    size: int
    pages: int | None
    description: str | None
    summary: str | None
    summary_source: str | None
    doc_date: str | None
    issuer: str | None
    amount: str | None
    tags: list[str] = []
    note: str | None
    category_id: int | None
    category_name: str | None = None
    suggested_category: str | None
    confidence: float | None
    needs_review: bool
    duplicate_of: int | None
    status: str
    is_favorite: bool
    position: float | None
    text_source: str | None
    text: str | None = None          # full text only from GET /documents/{id}
    file_url: str | None = None      # signed links: open inline / download / preview image
    download_url: str | None = None
    thumb_url: str | None = None
    already_saved: bool = False      # upload of a file that was saved before
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
