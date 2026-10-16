"""Async client for the DocVault server."""

from typing import Any

import httpx


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Offline(Exception):
    pass


class Api:
    def __init__(self, base_url: str = "", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def configure(self, base_url: str | None = None, token: str | None = None) -> None:
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if token is not None:
            self.token = token

    async def _req(self, method: str, path: str, timeout: float = 30, **kw) -> Any:
        if not self.base_url:
            raise Offline("No server configured")
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=headers) as c:
                r = await c.request(method, path, **kw)
        except httpx.TransportError as e:
            raise Offline(str(e)) from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ApiError(r.status_code, detail if isinstance(detail, str) else str(detail))
        return None if r.status_code == 204 else r.json()

    # account
    async def login(self, email: str, password: str) -> dict:
        return await self._req("POST", "/auth/login", json={"email": email, "password": password})

    async def register(self, email: str, password: str) -> dict:
        return await self._req("POST", "/auth/register", json={"email": email, "password": password})

    async def me(self) -> dict:
        return await self._req("GET", "/me")

    # documents
    async def documents(self, **params) -> dict:
        params.setdefault("limit", 1000)
        return await self._req("GET", "/documents", params={k: v for k, v in params.items() if v is not None})

    async def document(self, doc_id: int) -> dict:
        return await self._req("GET", f"/documents/{doc_id}")

    async def upload(self, data: bytes, filename: str) -> dict:
        return await self._req("POST", "/documents", timeout=180, files={"file": (filename, data)})

    async def update(self, doc_id: int, **changes) -> dict:
        return await self._req("PATCH", f"/documents/{doc_id}", json=changes)

    async def delete(self, doc_id: int) -> None:
        await self._req("DELETE", f"/documents/{doc_id}")

    async def refresh(self, doc_id: int) -> dict:
        return await self._req("POST", f"/documents/{doc_id}/refresh")

    # categories
    async def categories(self) -> list[dict]:
        return await self._req("GET", "/categories")

    async def create_category(self, name: str, icon: str, color: str) -> dict:
        return await self._req("POST", "/categories", json={"name": name, "icon": icon, "color": color})

    async def update_category(self, cat_id: int, **changes) -> dict:
        return await self._req("PATCH", f"/categories/{cat_id}", json=changes)

    async def delete_category(self, cat_id: int) -> None:
        await self._req("DELETE", f"/categories/{cat_id}")

    async def reorder_categories(self, ids: list[int]) -> list[dict]:
        return await self._req("POST", "/categories/reorder", json={"ids": ids})
