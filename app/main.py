"""DocVault app: runs on the PC (desktop window) and as the web page phones use (served by serve.py)."""

import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import flet as ft

import screens
import ui
from api import Api, ApiError, Offline

log = logging.getLogger("docvault")

TABS = ["/", "/search", "/review", "/settings"]
# Pre-filled server address on the PC app's login screen (the web app always uses its own server).
DEFAULT_SERVER = os.getenv("DOCVAULT_SERVER", "")
ALLOWED = ["pdf", "jpg", "jpeg", "png", "webp"]


def public_origin(url: str | None) -> str:
    """Web address the browser is on, from the session's connection URL (ws://host/app → https://host)."""
    p = urlparse(url or "")
    if not p.netloc:
        return ""
    host = p.hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1") or host.startswith(("192.168.", "10."))
    return f"{'https' if p.scheme in ('https', 'wss') or not local else 'http'}://{p.netloc}"


class DocVaultApp:
    def __init__(self, page: ft.Page, web_api: str | None = None):
        self.page = page
        self.web = web_api is not None
        self.api = Api(web_api or "")
        self.public_base = public_origin(page.url) if self.web else ""
        self.default_server = DEFAULT_SERVER
        self.email = ""
        self.api_key = ""
        self.docs: list[dict] = []
        self.cats: list[dict] = []
        self.details: dict[int, dict] = {}
        self.search_q = ""
        self.history: list[str] = []
        self._after: list = []
        self._cache: dict[str, tuple] = {}
        self._poll: asyncio.Task | None = None
        self._debounce: dict[str, asyncio.Task] = {}
        self._syncing = False
        # Thumbnails or list, chosen separately for Recent ("/") and for each category / Favorites /
        # Duplicates screen, and remembered on this device.
        self.views: dict[str, str] = {}
        # Services must be created inside main() so they register with this page.
        self.prefs = ft.SharedPreferences()
        self.launcher = ft.UrlLauncher()
        self.clipboard = ft.Clipboard()
        self.picker = ft.FilePicker()
        # After every event Flet removes services that look unreferenced, and on Python 3.12 one
        # attribute isn't enough: the phone then loses e.g. the link opener ("Timeout waiting for
        # invoke method listener"). A second reference keeps them for the whole session.
        self._keep_services = [self.prefs, self.launcher, self.clipboard, self.picker]

    # ------------------------------------------------------------ helpers

    @property
    def logged_in(self) -> bool:
        return bool(self.api.token)

    def run(self, coro) -> None:
        async def runner():
            await coro
        self.page.run_task(runner)

    def after_render(self, fn) -> None:
        self._after.append(fn)

    def debounce(self, key: str, seconds: float, coro_fn) -> None:
        if (t := self._debounce.get(key)) and not t.done():
            t.cancel()

        async def later():
            await asyncio.sleep(seconds)
            await coro_fn()
        self._debounce[key] = asyncio.create_task(later())

    def toast(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(message), duration=ft.Duration(seconds=4)))

    def nav_bar(self, index: int) -> ft.NavigationBar:
        n = sum(1 for d in self.docs if d.get("needs_review") and d.get("status") == "ready")
        return ft.NavigationBar(selected_index=index, on_change=lambda e: self.go(TABS[e.control.selected_index]),
                                destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="Home"),
            ft.NavigationBarDestination(icon=ft.Icons.SEARCH, label="Search"),
            ft.NavigationBarDestination(icon=ft.Icon(ft.Icons.INBOX_OUTLINED, badge=str(n) if n else None),
                                        selected_icon=ft.Icons.INBOX, label="Review"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Settings"),
        ])

    def sync_button(self) -> ft.Control:
        if self._syncing:
            return ft.Container(ft.ProgressRing(width=18, height=18, stroke_width=2), padding=14)
        return ft.IconButton(ft.Icons.SYNC, tooltip="Refresh", on_click=lambda: self.run(self.sync()))

    # ------------------------------------------------------------ navigation

    def _build(self, route: str) -> ft.View:
        if not self.logged_in or route == "/login":
            return screens.build_login(self)
        if route == "/search":
            return screens.build_search(self)
        if route == "/review":
            return screens.build_review(self)
        if route == "/settings":
            return screens.build_settings(self)
        if route.startswith("/doc/"):
            return screens.build_detail(self, route)
        if route.startswith("/category/") or route in ("/favorites", "/duplicates"):
            return screens.build_list(self, route)
        return screens.build_home(self)

    def _build_cached(self, route: str) -> ft.View:
        """A document's page is only rebuilt when that document changed, so refreshing in the
        background doesn't wipe what you're typing there."""
        if not route.startswith("/doc/"):
            return self._build(route)
        doc_id = int(route.rsplit("/", 1)[-1])
        d = self.details.get(doc_id) or next((x for x in self.docs if x["id"] == doc_id), {})
        key = (d.get("updated_at"), d.get("status"), d.get("category_id"), bool(d.get("text")), len(self.cats))
        if (hit := self._cache.get(route)) and hit[0] == key:
            return hit[1]
        view = self._build(route)
        self._cache[route] = (key, view)
        return view

    def render(self) -> None:
        if not self.history:
            self.history = ["/" if self.logged_in else "/login"]
        self.page.views.clear()
        self.page.views.extend(self._build_cached(r) for r in self.history)
        self.page.update()
        pending, self._after = self._after, []
        for fn in pending:
            self.run(fn())

    def go(self, route: str) -> None:
        if route in TABS or route == "/login":
            self.history = [route]
        elif not self.history or self.history[-1] != route:
            self.history.append(route)
            self._cache.pop(route, None)
        self.render()

    def refresh(self) -> None:
        self.render()

    async def on_view_pop(self, e) -> None:
        if len(self.history) > 1:
            self.history.pop()
        self.render()

    # ------------------------------------------------------------ account

    def add_button_args(self) -> dict:
        """How "Add documents" buttons behave. On the web page they open /add straight from the phone:
        iPhone Safari only shows the file chooser during the tap itself, and the app's own picker
        has to go via the server first, so Safari would ignore it."""
        if self.web:
            return {"url": ft.Url(f"{self.public_base}/add", target=ft.UrlTarget.SELF)}
        return {"on_click": lambda: self.run(self.pick_files())}

    async def restore_login(self) -> None:
        token = None
        for attempt in range(3):  # right after a server restart the browser can be slow to answer
            try:
                token = await self.prefs.get("dv_token")
                break
            except Exception as e:
                log.info("reading saved login failed (%s), retrying", e)
                await asyncio.sleep(1)
        if not token:
            return
        if not self.web:
            self.api.configure(base_url=await self.prefs.get("dv_server") or DEFAULT_SERVER)
        self.api.configure(token=token)
        self.email = await self.prefs.get("dv_email") or ""
        self.api_key = await self.prefs.get("dv_api_key") or ""
        self.views = await self._load_views()

    async def logged_in_as(self, email: str, res: dict) -> None:
        self.api.configure(token=res["access_token"])
        self.email, self.api_key = email, res["api_key"]
        await self.prefs.set("dv_token", res["access_token"])
        await self.prefs.set("dv_email", email)
        await self.prefs.set("dv_api_key", res["api_key"])
        if not self.web:
            await self.prefs.set("dv_server", self.api.base_url)
            ui.SERVER = self.api.base_url
        self.go("/")
        await self.sync()

    async def logout(self) -> None:
        for k in ("dv_token", "dv_email", "dv_api_key"):
            await self.prefs.remove(k)
        self.api.configure(token="")
        self.docs, self.cats, self.details = [], [], {}
        self.go("/login")

    # ------------------------------------------------------------ data

    async def sync(self) -> None:
        if not self.logged_in or self._syncing:
            return
        self._syncing = True
        self.refresh()
        try:
            self.cats = await self.api.categories()
            self.docs = (await self.api.documents())["items"]
        except Offline:
            self.toast("Can't reach the server right now")
        except ApiError as e:
            if e.status == 401:
                self.toast("Please log in again")
                self._syncing = False
                await self.logout()
                return
            self.toast(f"Couldn't load: {e.detail}")
        finally:
            self._syncing = False
        self.refresh()
        if any(d.get("status") == "processing" for d in self.docs):
            self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll and not self._poll.done():
            return

        async def poll():
            for delay in (2, 3, 5, 8, 13, 20, 30):
                await asyncio.sleep(delay)
                await self.sync()
                for doc_id in list(self.details):  # keep open documents up to date
                    await self.load_detail(doc_id, quiet=True)
                if not any(d.get("status") == "processing" for d in self.docs):
                    break
        self._poll = asyncio.create_task(poll())

    async def load_detail(self, doc_id: int, quiet: bool = False) -> None:
        try:
            self.details[doc_id] = await self.api.document(doc_id)
        except (Offline, ApiError) as e:
            if not quiet:
                self.toast(f"Couldn't open the document: {e}")
            return
        self.refresh()

    async def pick_files(self) -> None:
        files = await self.picker.pick_files(dialog_title="Add documents", allow_multiple=True,
                                             file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=ALLOWED,
                                             with_data=self.web or self.page.platform not in (
                                                 ft.PagePlatform.WINDOWS, ft.PagePlatform.MACOS, ft.PagePlatform.LINUX))
        if not files:
            return
        added = again = 0
        for f in files:
            try:
                data = f.bytes if f.bytes else Path(f.path).read_bytes()
                doc = await self.api.upload(data, f.name)
            except (Offline, ApiError, OSError) as e:
                self.toast(f"Couldn't add {f.name}: {e}")
                continue
            again += doc.get("already_saved", False)
            added += not doc.get("already_saved", False)
        msg = f"Added {added} document{'s' * (added != 1)}" if added else ""
        if again:
            msg += (" · " if msg else "") + f"{again} already saved"
        if msg:
            self.toast(msg + (" ✓" if added else ""))
        await self.sync()

    # ------------------------------------------------------------ views & drag to reorder

    def view_for(self, route: str) -> str:
        return self.views.get(route, "thumbs")

    async def set_view(self, route: str, mode: str) -> None:
        self.views[route] = mode
        self._cache.clear()
        self.refresh()
        try:
            await self.prefs.set("dv_views", json.dumps(self.views))
        except Exception:
            pass

    async def _load_views(self) -> dict[str, str]:
        try:
            saved = await self.prefs.get("dv_views")
            if saved:
                return {k: v for k, v in json.loads(saved).items() if v in ("thumbs", "list")}
            old = await self.prefs.get("dv_view")  # earlier versions had one setting for everything
            return {"/": old} if old in ("thumbs", "list") else {}
        except Exception:
            return {}

    @property
    def drag_affinity(self) -> ft.Axis | None:
        """On phones a vertical swipe must still scroll, so dragging a tile starts with a sideways move."""
        touch = self.page.platform in (ft.PagePlatform.IOS, ft.PagePlatform.ANDROID)
        return ft.Axis.HORIZONTAL if touch else None

    @staticmethod
    def position_between(above: float | None, below: float | None) -> float | None:
        """Positions sort high to low, so a card dropped between two others gets the midpoint."""
        if above is None and below is None:
            return None
        if above is None:
            return below + 1.0
        if below is None:
            return above - 1.0
        return (above + below) / 2

    def move_doc(self, items: list[dict], old: int, new: int) -> None:
        if old == new or not 0 <= old < len(items):
            return
        items = list(items)
        moved = items.pop(old)
        new = max(0, min(new, len(items)))
        items.insert(new, moved)
        above = items[new - 1].get("position") if new > 0 else None
        below = items[new + 1].get("position") if new + 1 < len(items) else None
        position = self.position_between(above, below)
        if position is None:
            return
        moved["position"] = position  # show the new order straight away
        self.docs.sort(key=lambda d: -(d.get("position") or 0))
        self.refresh()

        async def save():
            try:
                await self.api.update(moved["id"], position=position)
            except (Offline, ApiError) as e:
                self.toast(f"Couldn't save the new order: {e}")
                await self.sync()
        self.run(save())

    def move_doc_onto(self, items: list[dict], source_id: int, target_id: int) -> None:
        """Thumbnail grids: a document dropped onto another takes its place."""
        ids = [d["id"] for d in items]
        if source_id == target_id or source_id not in ids or target_id not in ids:
            return
        self.move_doc(items, ids.index(source_id), ids.index(target_id))

    def move_category(self, source_id: int, target_id: int) -> None:
        ids = [c["id"] for c in self.cats]
        if source_id == target_id or source_id not in ids or target_id not in ids:
            return
        target_index = ids.index(target_id)
        ids.remove(source_id)
        ids.insert(target_index, source_id)
        by_id = {c["id"]: c for c in self.cats}
        self.cats = [by_id[i] for i in ids]
        self.refresh()

        async def save():
            try:
                self.cats = await self.api.reorder_categories(ids)
            except (Offline, ApiError) as e:
                self.toast(f"Couldn't save the category order: {e}")
        self.run(save())

    async def update(self, doc_id: int, **changes) -> None:
        try:
            d = await self.api.update(doc_id, **changes)
        except (Offline, ApiError) as e:
            self.toast(str(e))
            return
        self.details.pop(doc_id, None)
        self.docs = [d if x["id"] == doc_id else x for x in self.docs]
        if "category" in changes or "category_id" in changes:
            self.cats = await self.api.categories()
        self.refresh()
        if self.history and self.history[-1] == f"/doc/{doc_id}":
            await self.load_detail(doc_id, quiet=True)

    async def delete(self, doc_id: int, go_back: bool = False) -> None:
        try:
            await self.api.delete(doc_id)
        except (Offline, ApiError) as e:
            self.toast(str(e))
            return
        if go_back and self.history and self.history[-1] == f"/doc/{doc_id}":
            self.history.pop()
        self.toast("Deleted")
        await self.sync()

    async def refresh_doc(self, doc_id: int) -> None:
        try:
            await self.api.refresh(doc_id)
        except (Offline, ApiError) as e:
            self.toast(str(e))
            return
        self.details.pop(doc_id, None)
        await self.sync()

    def open_file(self, d: dict) -> None:
        self.run(self.launcher.launch_url(ui.resolve(d["file_url"]), mode=ft.LaunchMode.EXTERNAL_APPLICATION))

    def download(self, d: dict) -> None:
        self.run(self.launcher.launch_url(ui.resolve(d["download_url"]), mode=ft.LaunchMode.EXTERNAL_APPLICATION))

    async def copy(self, text: str, message: str) -> None:
        await self.clipboard.set(text)
        self.toast(message)


async def main(page: ft.Page, web_api: str | None = None):
    logging.basicConfig(level=logging.INFO)
    page.title = "DocVault"
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
    app = DocVaultApp(page, web_api)
    page.on_view_pop = app.on_view_pop

    async def on_lifecycle(e: ft.AppLifecycleStateChangeEvent):
        if e.state == ft.AppLifecycleState.RESUME:
            await app.sync()
    page.on_app_lifecycle_state_change = on_lifecycle

    await app.restore_login()
    ui.SERVER = app.public_base if app.web else app.api.base_url
    app.render()
    await app.sync()


async def web_main(page: ft.Page):
    """Entry point when the server serves the app as a web page (serve.py)."""
    await main(page, web_api=os.getenv("DOCVAULT_API", "http://127.0.0.1:8001"))


if __name__ == "__main__":
    ft.run(main)
