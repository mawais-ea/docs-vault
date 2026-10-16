"""Run DocVault: the API plus the app as a web page at /app.

    .venv\\Scripts\\python -m uvicorn serve:app --host 127.0.0.1 --port 8001

  /          redirects to /app/
  /app/      your documents in any browser (iPhone: Safari > Share > Add to Home Screen)
  /u/<key>   iPhone Shortcut upload: POST the file as the request body
"""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "app"))      # the Flet app: main.py, screens.py, ui.py, api.py
sys.path.insert(0, str(ROOT / "backend"))  # the API: package "app"
os.chdir(ROOT / "backend")                 # .env, docvault.db and files/ live here

import flet_web.fastapi as flet_fastapi  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from app.main import app  # noqa: E402  (the API)
import main as docvault  # noqa: E402  (the Flet app)

app.mount("/app", flet_fastapi.app(
    docvault.web_main, assets_dir=str(ROOT / "app" / "assets"),
    app_name="DocVault", app_short_name="DocVault", app_description="Your documents, read and filed for you",
))


@app.get("/", include_in_schema=False)
def _home():
    return RedirectResponse("/app/")


_api_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(a):
    async with _api_lifespan(a):
        await flet_fastapi.app_manager.start()
        try:
            yield
        finally:
            await flet_fastapi.app_manager.shutdown()


app.router.lifespan_context = _lifespan
