import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routers import account, add_page, categories, documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class _HideApiKeys(logging.Filter):
    """Upload links carry the API key in the address; keep it out of the access log."""
    _pattern = re.compile(r"(/u/)dv_[A-Za-z0-9_\-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._pattern.sub(r"\1dv_***", a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_HideApiKeys())


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="DocVault API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(account.router)
app.include_router(documents.router)
app.include_router(categories.router)
app.include_router(add_page.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
