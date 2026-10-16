"""All the screens. Each build_* returns an ft.View for one route."""

from typing import TYPE_CHECKING

import flet as ft

from api import ApiError, Offline
from ui import (category_dialog, doc_card, doc_tile, empty_state, icon, move_dialog, preview, pretty_date,
                pretty_size, rename_dialog, split_name)

if TYPE_CHECKING:
    from main import DocVaultApp

PAD = ft.Padding.only(left=16, top=16, right=26, bottom=16)  # room on the right for the scrollbar
TILE_COLS = {"xs": 6, "sm": 4, "md": 3, "lg": 2}


def _header(title: str, *actions: ft.Control) -> ft.Control:
    return ft.Row([ft.Text(title, size=18, weight=ft.FontWeight.BOLD, expand=True), *actions])


# ---------------------------------------------------------------- home

def category_tile(app: "DocVaultApp", c: dict, width: float | None = None) -> ft.Container:
    return ft.Container(
        width=width, padding=14, border_radius=16, ink=True, bgcolor=ft.Colors.with_opacity(0.14, c["color"]),
        border=ft.Border.all(2, ft.Colors.TRANSPARENT),
        on_click=lambda: app.go(f"/category/{c['id']}"),
        content=ft.Column([
            ft.Icon(icon(c["icon"]), color=c["color"], size=28),
            ft.Text(c["name"], weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{c['count']} document{'s' * (c['count'] != 1)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=4),
    )


def _drop_target(app: "DocVaultApp", group: str, item_id: int, make, on_drop, col=None,
                 feedback_width: float = 160) -> ft.Control:
    """A tile that can be dragged, and that other tiles of the same group can be dropped on.

    `make(width)` builds the tile; it's called separately for the tile itself and for the copy
    that follows your finger (a control can only be shown in one place at a time)."""
    tile = make(None)

    def lit(on: bool):
        tile.border = ft.Border.all(2, ft.Colors.PRIMARY if on else ft.Colors.TRANSPARENT)
        tile.update()

    def accept(e):
        lit(False)
        source = e.src if getattr(e, "src", None) is not None else app.page.get_control(e.src_id)
        on_drop(int(source.data), item_id)

    return ft.DragTarget(
        group=group, col=col, data=item_id,
        on_will_accept=lambda e: lit(bool(e.accept)), on_leave=lambda e: lit(False), on_accept=accept,
        content=ft.Draggable(
            group=group, data=item_id, content=tile, affinity=app.drag_affinity,
            content_when_dragging=ft.Container(height=100, border_radius=16,
                                               border=ft.Border.all(2, ft.Colors.OUTLINE_VARIANT)),
            content_feedback=ft.Container(make(feedback_width), opacity=0.9)),
    )


def draggable_category_tile(app: "DocVaultApp", c: dict) -> ft.Control:
    return _drop_target(app, "category", c["id"], lambda w: category_tile(app, c, width=w), app.move_category,
                        col=TILE_COLS, feedback_width=170)


def view_switch(app: "DocVaultApp") -> ft.Control:
    """Thumbnails / list toggle (remembered on this device)."""
    def button(ic, mode, tip):
        on = app.view == mode
        return ft.IconButton(ic, tooltip=tip, on_click=lambda: app.run(app.set_view(mode)),
                             icon_color=ft.Colors.PRIMARY if on else ft.Colors.ON_SURFACE_VARIANT,
                             bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY) if on else None)
    return ft.Row([button(ft.Icons.GRID_VIEW, "thumbs", "Thumbnails"),
                   button(ft.Icons.VIEW_LIST, "list", "List")], spacing=0)


def reorderable(app: "DocVaultApp", items: list[dict], make, **kwargs) -> ft.ReorderableListView:
    """Cards that can be dragged into a new order: drag handle on a PC, press-and-hold on a phone."""
    controls = [make(d) for d in items]
    for d, c in zip(items, controls):
        c.key = f"doc-{d['id']}"
    return ft.ReorderableListView(controls=controls, scroll=ft.ScrollMode.ALWAYS,
                                  on_reorder=lambda e: app.move_doc(items, e.old_index, e.new_index), **kwargs)


def thumb_grid(app: "DocVaultApp", items: list[dict]) -> ft.Control:
    """Thumbnail grid; drop a document onto another to take its place."""
    cells = [_drop_target(app, "doc", d["id"], lambda w, d=d: doc_tile(app, d, grid=True, width=w),
                          lambda src, dst: app.move_doc_onto(items, src, dst), col={"xs": 6, "sm": 4, "md": 3, "lg": 2},
                          feedback_width=130)
             for d in items]
    return ft.ResponsiveRow(cells, spacing=12, run_spacing=12)


def build_home(app: "DocVaultApp") -> ft.View:
    recent = app.docs[:12]
    dups = [d for d in app.docs if d.get("duplicate_of")]
    top: list[ft.Control] = [
        ft.Row([
            ft.FilledButton("Add documents", icon=ft.Icons.UPLOAD_FILE, **app.add_button_args()),
            ft.OutlinedButton("Search", icon=ft.Icons.SEARCH, on_click=lambda: app.go("/search")),
        ], wrap=True),
    ]
    strip: ft.Control | None = None
    if not app.docs:
        top.append(empty_state(ft.Icons.FOLDER_OPEN, "No documents yet.\nTap “Add documents”, or share a PDF or "
                               "photo to DocVault from your phone."))
    else:
        top.append(_header("Recent", view_switch(app)))
        if app.view == "thumbs":
            strip = reorderable(app, recent, lambda d: doc_tile(app, d), horizontal=True, height=250)

    bottom: list[ft.Control] = []
    if dups:
        bottom.append(ft.Container(
            padding=12, border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW, ink=True,
            on_click=lambda: app.go("/duplicates"),
            content=ft.Row([ft.Icon(ft.Icons.CONTENT_COPY), ft.Text(
                f"{len(dups)} possible duplicate{'s' * (len(dups) != 1)}: same content saved more than once",
                expand=True), ft.Icon(ft.Icons.CHEVRON_RIGHT)])))
    bottom += [
        _header("Categories", ft.TextButton("New category", icon=ft.Icons.ADD, on_click=lambda: category_dialog(app))),
        ft.Text("Drag a tile onto another to rearrange.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ft.ResponsiveRow([draggable_category_tile(app, c) for c in app.cats], spacing=10, run_spacing=10),
    ]
    common = dict(
        route="/", appbar=ft.AppBar(title=ft.Text("DocVault"), actions=[
            ft.IconButton(ft.Icons.STAR, tooltip="Favorites", on_click=lambda: app.go("/favorites")),
            app.sync_button()]),
        navigation_bar=app.nav_bar(0),
        floating_action_button=ft.FloatingActionButton(icon=ft.Icons.UPLOAD_FILE, tooltip="Add documents",
                                                       **app.add_button_args()),
    )
    if app.view == "list" and recent:
        # One draggable list for the page; the rest rides along as its header and footer.
        return ft.View(**common, padding=ft.Padding.only(left=16, top=16, right=16, bottom=0), controls=[
            reorderable(app, recent[:8], lambda d: doc_card(app, d), expand=True,
                        header=ft.Column(top, spacing=12), padding=ft.Padding.only(right=10),
                        footer=ft.Container(ft.Column(bottom, spacing=12), padding=ft.Padding.only(top=12, bottom=90))),
        ])
    return ft.View(**common, scroll=ft.ScrollMode.ALWAYS, padding=PAD,
                   controls=top + ([strip] if strip else []) + bottom)


def build_list(app: "DocVaultApp", route: str) -> ft.View:
    """A category, Favorites or Duplicates: thumbnails or list, drag to reorder in both."""
    if route == "/favorites":
        title, items = "Favorites", [d for d in app.docs if d.get("is_favorite")]
    elif route == "/duplicates":
        title, items = "Possible duplicates", [d for d in app.docs if d.get("duplicate_of")]
    else:
        cat_id = int(route.rsplit("/", 1)[-1])
        title = next((c["name"] for c in app.cats if c["id"] == cat_id), "Category")
        items = [d for d in app.docs if d.get("category_id") == cat_id]
    appbar = ft.AppBar(title=ft.Text(title), actions=[view_switch(app), app.sync_button()])
    if not items:
        return ft.View(route=route, appbar=appbar, padding=PAD, controls=[empty_state(ft.Icons.INBOX, "Nothing here yet.")])
    show_cat = route in ("/favorites", "/duplicates")
    if app.view == "thumbs":
        return ft.View(route=route, appbar=appbar, scroll=ft.ScrollMode.ALWAYS, padding=PAD, controls=[
            ft.Text("Drag a document onto another to move it there.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            thumb_grid(app, items)])
    return ft.View(route=route, appbar=appbar, padding=ft.Padding.only(left=12, top=12, right=12, bottom=0), controls=[
        reorderable(app, items, lambda d: doc_card(app, d, show_category=show_cat), expand=True,
                    padding=ft.Padding.only(right=10, bottom=24))])


# ---------------------------------------------------------------- search

def build_search(app: "DocVaultApp") -> ft.View:
    results = ft.Column(spacing=4)

    async def run(q: str):
        app.search_q = q
        if not q.strip():
            results.controls = [empty_state(ft.Icons.SEARCH, "Search inside every document: names, amounts, "
                                            "account and policy numbers, anything written in them.")]
        else:
            try:
                found = (await app.api.documents(q=q.strip(), limit=200))["items"]
            except (ApiError, Offline) as e:
                found = []
                app.toast(f"Search failed: {e}")
            results.controls = ([ft.Text(f"{len(found)} result{'s' * (len(found) != 1)}", size=12)]
                                + [doc_card(app, d) for d in found]) or [empty_state(ft.Icons.SEARCH_OFF, "No matches.")]
        results.update()

    box = ft.TextField(value=app.search_q, hint_text="Search everything", prefix_icon=ft.Icons.SEARCH, autofocus=True,
                       border=ft.OutlineInputBorder(border_radius=24), on_submit=lambda e: app.run(run(e.control.value or "")),
                       on_change=lambda e: app.debounce("search", 0.5, lambda: run(e.control.value or "")))
    app.after_render(lambda: run(app.search_q))
    return ft.View(route="/search", appbar=ft.AppBar(title=ft.Text("Search")), navigation_bar=app.nav_bar(1),
                   scroll=ft.ScrollMode.ALWAYS, padding=PAD,
                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[box, results])


# ---------------------------------------------------------------- review

def build_review(app: "DocVaultApp") -> ft.View:
    items = [d for d in app.docs if d.get("needs_review") and d.get("status") == "ready"]
    by_use = sorted(app.cats, key=lambda c: -c["count"])
    blocks = []
    for d in items:
        chips: list[ft.Control] = []
        if d.get("suggested_category"):
            chips.append(ft.Chip(label=ft.Text(f"Create “{d['suggested_category']}”"), leading=ft.Icon(ft.Icons.ADD, size=16),
                                 on_click=lambda e, d=d: app.run(app.update(d["id"], category=d["suggested_category"]))))
        if d.get("category_name"):
            chips.append(ft.Chip(label=ft.Text(f"Keep in {d['category_name']}"), leading=ft.Icon(ft.Icons.CHECK, size=16),
                                 on_click=lambda e, d=d: app.run(app.update(d["id"], needs_review=False))))
        for c in [c for c in by_use if c["id"] != d.get("category_id")][:6]:
            chips.append(ft.Chip(label=ft.Text(c["name"]), leading=ft.Icon(icon(c["icon"]), size=16, color=c["color"]),
                                 on_click=lambda e, d=d, c=c: app.run(app.update(d["id"], category_id=c["id"]))))
        chips.append(ft.Chip(label=ft.Text("Other…"), on_click=lambda e, d=d: move_dialog(app, d)))
        blocks.append(ft.Column([doc_card(app, d), ft.Row(chips, wrap=True, spacing=6)], spacing=4))
    return ft.View(route="/review", appbar=ft.AppBar(title=ft.Text("Review")), navigation_bar=app.nav_bar(2),
                   scroll=ft.ScrollMode.ALWAYS, padding=PAD, controls=blocks or [
                       empty_state(ft.Icons.TASK_ALT, "All sorted. Documents DocVault isn't sure about appear here.")])


# ---------------------------------------------------------------- one document

def _fact(label: str, value: str | None) -> ft.Control | None:
    if not value:
        return None
    return ft.Row([ft.Text(label, width=90, color=ft.Colors.ON_SURFACE_VARIANT),
                   ft.Text(value, selectable=True, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START)


def build_detail(app: "DocVaultApp", route: str) -> ft.View:
    doc_id = int(route.rsplit("/", 1)[-1])
    d = app.details.get(doc_id) or next((x for x in app.docs if x["id"] == doc_id), None)
    if not d:
        app.after_render(lambda: app.load_detail(doc_id))
        return ft.View(route=route, appbar=ft.AppBar(title=ft.Text("Document")),
                       controls=[ft.Container(ft.ProgressRing(), alignment=ft.Alignment.CENTER, padding=40)])
    if doc_id not in app.details:
        app.after_render(lambda: app.load_detail(doc_id))

    title = ft.TextField(label="Name in DocVault", value=d.get("title") or "", multiline=True, max_lines=None)
    stem, ext = split_name(d.get("suggested_name") or d.get("original_name"))
    file_name = ft.TextField(label="File name", value=stem, suffix=ext,
                             helper="Used when you download or share it")
    note = ft.TextField(label="Your note", value=d.get("note") or "", multiline=True, min_lines=2, max_lines=None)
    category = ft.Dropdown(label="Category", value=str(d["category_id"]) if d.get("category_id") else None,
                           options=[ft.DropdownOption(key=str(c["id"]), text=c["name"]) for c in app.cats])

    async def save():
        changes = {}
        if (title.value or "").strip() and title.value.strip() != (d.get("title") or ""):
            changes["title"] = title.value.strip()
        if (file_name.value or "").strip() and file_name.value.strip() + ext != (d.get("suggested_name") or ""):
            changes["file_name"] = file_name.value.strip()
        if (note.value or "") != (d.get("note") or ""):
            changes["note"] = note.value
        if category.value and int(category.value) != d.get("category_id"):
            changes["category_id"] = int(category.value)
        if changes:
            await app.update(doc_id, **changes)
            app.toast("Saved")

    controls: list[ft.Control] = [
        ft.Container(content=preview(d, 300, 400), alignment=ft.Alignment.CENTER, ink=True,
                     on_click=lambda: app.open_file(d)),
        ft.Row([
            ft.FilledButton("Open", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda: app.open_file(d)),
            ft.OutlinedButton("Download", icon=ft.Icons.DOWNLOAD, on_click=lambda: app.download(d)),
        ], wrap=True, alignment=ft.MainAxisAlignment.CENTER),
    ]
    if d.get("status") == "processing":
        controls.append(ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2),
                                ft.Text("Reading this document…")], spacing=10))
    if d.get("duplicate_of"):
        controls.append(ft.Container(padding=12, border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW, ink=True,
                                     on_click=lambda: app.go(f"/doc/{d['duplicate_of']}"),
                                     content=ft.Row([ft.Icon(ft.Icons.CONTENT_COPY),
                                                     ft.Text("Same content as another document you saved. Tap to see it.",
                                                             expand=True)])))
    facts = [f for f in (
        _fact("From", d.get("issuer")), _fact("Date", pretty_date(d.get("doc_date"))), _fact("Amount", d.get("amount")),
        _fact("Original", d.get("original_name")),
        _fact("Size", f"{pretty_size(d.get('size'))}" + (
            f" · {d['pages']} page{'s' * (d['pages'] != 1)}" if d.get("pages") and d.get("kind") == "pdf" else "")),
        _fact("Saved", pretty_date(d.get("created_at"))),
    ) if f]
    controls.append(ft.Container(padding=14, border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                                 content=ft.Column(facts, spacing=6)))
    if d.get("summary"):
        label = "Found automatically · add a Claude API key for full summaries" if d.get("summary_source") == "quick" else ""
        controls.append(ft.Container(padding=14, border_radius=12, bgcolor=ft.Colors.SURFACE_CONTAINER_LOW, content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, size=20), ft.Text("Summary", weight=ft.FontWeight.BOLD, size=16),
                    ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True)]),
            ft.Markdown(d["summary"], selectable=True),
        ], spacing=8)))
    controls += [title, file_name, category, note,
                 ft.Row([ft.FilledButton("Save changes", icon=ft.Icons.CHECK, on_click=lambda: app.run(save()))],
                        alignment=ft.MainAxisAlignment.END)]
    if d.get("text"):
        source = {"pdf": "from the PDF", "ocr": "read from the image (OCR)"}.get(d.get("text_source"), "")
        controls.append(ft.ExpansionTile(
            title=ft.Text("Text in document"), subtitle=ft.Text(source, size=12),
            controls=[ft.Container(ft.Text(d["text"][:50000], selectable=True, size=13), padding=12)]))

    fav = d.get("is_favorite")
    return ft.View(
        route=route, padding=PAD, scroll=ft.ScrollMode.ALWAYS, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        appbar=ft.AppBar(title=ft.Text(d.get("title") or "Document", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                         actions=[
            ft.IconButton(ft.Icons.STAR if fav else ft.Icons.STAR_BORDER, tooltip="Favorite",
                          icon_color=ft.Colors.AMBER if fav else None,
                          on_click=lambda: app.run(app.update(doc_id, is_favorite=not fav))),
            ft.IconButton(ft.Icons.DRIVE_FILE_RENAME_OUTLINE, tooltip="Rename", on_click=lambda: rename_dialog(app, d)),
            ft.IconButton(ft.Icons.REFRESH, tooltip="Read and sort again", on_click=lambda: app.run(app.refresh_doc(doc_id))),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Delete", on_click=lambda: app.run(app.delete(doc_id, go_back=True))),
        ]),
        controls=controls,
    )


# ---------------------------------------------------------------- settings & login

def build_settings(app: "DocVaultApp") -> ft.View:
    key = app.api_key
    base = app.public_base or app.api.base_url
    controls = [
        ft.Text("Account", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
        ft.ListTile(leading=ft.Icon(ft.Icons.PERSON), title=ft.Text(app.email or "—"), subtitle=ft.Text(base)),
        ft.ListTile(leading=ft.Icon(ft.Icons.KEY), title=ft.Text("API key"),
                    subtitle=ft.Text("For the iPhone “Save to DocVault” shortcut"),
                    trailing=ft.IconButton(ft.Icons.CONTENT_COPY, tooltip="Copy API key",
                                           on_click=lambda: app.run(app.copy(key, "API key copied")))),
        ft.ListTile(leading=ft.Icon(ft.Icons.LINK), title=ft.Text("iPhone upload address"),
                    subtitle=ft.Text(f"{base}/u/{key[:6]}…", selectable=True),
                    trailing=ft.IconButton(ft.Icons.CONTENT_COPY, tooltip="Copy the full upload address",
                                           on_click=lambda: app.run(app.copy(f"{base}/u/{key}", "Upload address copied")))),
        ft.Text("Categories", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
        *[ft.ListTile(leading=ft.Icon(icon(c["icon"]), color=c["color"]), title=ft.Text(c["name"]),
                      subtitle=ft.Text(f"{c['count']} documents"), on_click=lambda e, c=c: category_dialog(app, c))
          for c in app.cats],
        ft.TextButton("Add category", icon=ft.Icons.ADD, on_click=lambda: category_dialog(app)),
        ft.TextButton("Log out", icon=ft.Icons.LOGOUT, on_click=lambda: app.run(app.logout())),
    ]
    return ft.View(route="/settings", appbar=ft.AppBar(title=ft.Text("Settings")), navigation_bar=app.nav_bar(3),
                   scroll=ft.ScrollMode.ALWAYS, padding=PAD, controls=controls)


def build_login(app: "DocVaultApp") -> ft.View:
    server = ft.TextField(label="Server URL", value=app.api.base_url or app.default_server, visible=not app.web,
                          keyboard_type=ft.KeyboardType.URL)
    email = ft.TextField(label="Email", value=app.email or "", keyboard_type=ft.KeyboardType.EMAIL)
    password = ft.TextField(label="Password", password=True, can_reveal_password=True)
    error = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def submit(register: bool):
        error.visible = False
        app.page.update()
        if not app.web:
            app.api.configure(base_url=(server.value or "").strip())
        try:
            fn = app.api.register if register else app.api.login
            res = await fn((email.value or "").strip(), password.value or "")
        except Offline:
            error.value = "Can't reach the server. Check the address and your connection."
        except ApiError as e:
            error.value = e.detail
        else:
            await app.logged_in_as((email.value or "").strip(), res)
            return
        error.visible = True
        app.page.update()

    password.on_submit = lambda: app.run(submit(False))
    return ft.View(route="/login", padding=24, scroll=ft.ScrollMode.ALWAYS,
                   vertical_alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   controls=[ft.Container(width=420, content=ft.Column([
                       ft.Icon(ft.Icons.FOLDER_SPECIAL, size=56, color=ft.Colors.PRIMARY),
                       ft.Text("DocVault", size=28, weight=ft.FontWeight.BOLD),
                       ft.Text("Your documents, read and filed for you.", color=ft.Colors.ON_SURFACE_VARIANT),
                       server, email, password, error,
                       ft.Row([ft.TextButton("Create account", on_click=lambda: app.run(submit(True))),
                               ft.FilledButton("Log in", on_click=lambda: app.run(submit(False)))],
                              alignment=ft.MainAxisAlignment.END),
                   ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=12))])
