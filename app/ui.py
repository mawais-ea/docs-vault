"""Shared UI pieces: document cards, icons, previews, dialogs."""

from datetime import date
from typing import TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from main import DocVaultApp

SERVER = ""  # base for signed file/preview links (/f/...); set by the app


def resolve(url: str | None) -> str | None:
    return SERVER.rstrip("/") + url if url and url.startswith("/") else url


def icon(name: str | None) -> ft.Icons:
    return getattr(ft.Icons, (name or "folder").upper(), ft.Icons.FOLDER)


def pretty_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso[:10]).strftime("%d %b %Y")
    except ValueError:
        return iso


def pretty_size(n: int | None) -> str:
    n = n or 0
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def facts_line(d: dict) -> str:
    bits = [d.get("issuer"), pretty_date(d.get("doc_date")), d.get("amount")]
    return " · ".join(b for b in bits if b)


def preview(d: dict, width: int, height: int) -> ft.Control:
    """First page (or the photo); a document icon behind it shows if the image can't load."""
    fallback = ft.Container(
        width=width, height=height, border_radius=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(ft.Icons.PICTURE_AS_PDF if d.get("kind") == "pdf" else ft.Icons.IMAGE, size=width // 3),
    )
    if not d.get("thumb_url"):
        return fallback
    return ft.Stack([
        fallback,
        # Pages fill the card; photos (often landscape) are shown whole.
        ft.Image(src=resolve(d["thumb_url"]), width=width, height=height, border_radius=8,
                 fit=ft.BoxFit.COVER if d.get("kind") == "pdf" else ft.BoxFit.CONTAIN,
                 error_content=ft.Container(width=width, height=height)),
    ], width=width, height=height)


def status_row(d: dict) -> ft.Control | None:
    if d.get("status") == "processing":
        return ft.Row([ft.ProgressRing(width=12, height=12, stroke_width=2), ft.Text("Reading…", size=11)], spacing=6)
    if d.get("status") == "failed":
        return ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, size=14, color=ft.Colors.ERROR),
                       ft.Text("Couldn't read this file", size=11)], spacing=6)
    return None


def doc_menu(app: "DocVaultApp", d: dict, icon_color=None) -> ft.PopupMenuButton:
    return ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT, icon_color=icon_color, tooltip="Options",
        items=[
            ft.PopupMenuItem(content="Open", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda: app.open_file(d)),
            ft.PopupMenuItem(content="Download", icon=ft.Icons.DOWNLOAD, on_click=lambda: app.download(d)),
            ft.PopupMenuItem(content="Unfavorite" if d.get("is_favorite") else "Favorite", icon=ft.Icons.STAR_BORDER,
                             on_click=lambda: app.run(app.update(d["id"], is_favorite=not d.get("is_favorite")))),
            ft.PopupMenuItem(content="Rename", icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE, on_click=lambda: rename_dialog(app, d)),
            ft.PopupMenuItem(content="Move to…", icon=ft.Icons.DRIVE_FILE_MOVE, on_click=lambda: move_dialog(app, d)),
            ft.PopupMenuItem(content="Delete", icon=ft.Icons.DELETE_OUTLINE,
                             on_click=lambda: app.run(app.delete(d["id"]))),
        ],
    )


def doc_card(app: "DocVaultApp", d: dict, show_category: bool = True) -> ft.Control:
    meta = [ft.Icon(ft.Icons.PICTURE_AS_PDF if d.get("kind") == "pdf" else ft.Icons.IMAGE, size=14)]
    if show_category and d.get("category_name"):
        meta.append(ft.Text(d["category_name"], size=11))
    if d.get("pages") and d.get("kind") == "pdf":
        meta.append(ft.Text(f"{d['pages']} page{'s' * (d['pages'] != 1)}", size=11))
    if d.get("is_favorite"):
        meta.append(ft.Icon(ft.Icons.STAR, size=14, color=ft.Colors.AMBER))
    if d.get("duplicate_of"):
        meta.append(ft.Icon(ft.Icons.CONTENT_COPY, size=14, tooltip="Looks like a copy of another document"))
    body: list[ft.Control] = [
        ft.Text(d.get("title") or d.get("original_name") or "Document", weight=ft.FontWeight.W_600, max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS),
    ]
    if facts := facts_line(d):
        body.append(ft.Text(facts, size=13, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS))
    body.append(status_row(d) or ft.Row(meta, spacing=6, wrap=True))
    return ft.Card(content=ft.Container(
        padding=10, border_radius=12, ink=True,
        on_click=lambda: app.go(f"/doc/{d['id']}"),
        on_long_press=lambda: move_dialog(app, d),
        content=ft.Row([preview(d, 60, 80), ft.Column(body, spacing=4, expand=True), doc_menu(app, d)],
                       vertical_alignment=ft.CrossAxisAlignment.START, spacing=12),
    ))


def doc_tile(app: "DocVaultApp", d: dict, grid: bool = False, width: float | None = None) -> ft.Container:
    """Portrait card for the Recent strip and thumbnail grids, with the same ⋮ menu."""
    pic = ft.Stack([
        preview(d, 120, 160),
        ft.Container(doc_menu(app, d, icon_color=ft.Colors.WHITE), right=2, top=2, width=36, height=36,
                     border_radius=18, bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                     alignment=ft.Alignment.CENTER),
    ], width=120, height=160)
    return ft.Container(
        width=width or (None if grid else 120), margin=None if grid else ft.Margin.only(right=12),
        padding=ft.Padding.all(6) if grid else ft.Padding.only(bottom=16), ink=True, border_radius=10,
        border=ft.Border.all(2, ft.Colors.TRANSPARENT),
        on_click=lambda: app.go(f"/doc/{d['id']}"),
        content=ft.Column([pic, ft.Text(d.get("title") or "Document", size=12, max_lines=2,
                                        overflow=ft.TextOverflow.ELLIPSIS)],
                          spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER if grid else ft.CrossAxisAlignment.START),
    )


def split_name(file_name: str | None) -> tuple[str, str]:
    """'2026-10-03 British Gas Bill.pdf' -> ('2026-10-03 British Gas Bill', '.pdf')"""
    if not file_name or "." not in file_name:
        return file_name or "", ""
    stem, ext = file_name.rsplit(".", 1)
    return stem, "." + ext


def rename_dialog(app: "DocVaultApp", d: dict) -> None:
    """Change what it's called in the app and the name it downloads/shares with."""
    stem, ext = split_name(d.get("suggested_name") or d.get("original_name"))
    title = ft.TextField(label="Name in DocVault", value=d.get("title") or "", autofocus=True)
    file_name = ft.TextField(label="File name", value=stem, suffix=ext,
                             helper="Used when you download or share it")
    same = ft.Checkbox(label="Use the same name for both", value=False)

    def sync_names(e=None):
        if same.value:
            file_name.value = title.value
            file_name.update()
    same.on_change = sync_names
    title.on_change = sync_names

    async def save():
        changes = {}
        if (title.value or "").strip() and title.value.strip() != (d.get("title") or ""):
            changes["title"] = title.value.strip()
        if (file_name.value or "").strip() and (file_name.value.strip() + ext) != (d.get("suggested_name") or ""):
            changes["file_name"] = file_name.value.strip()
        app.page.pop_dialog()
        if changes:
            await app.update(d["id"], **changes)
            app.toast("Renamed")

    app.page.show_dialog(ft.AlertDialog(
        title=ft.Text("Rename"),
        content=ft.Column([title, file_name, same], tight=True, width=380),
        actions=[ft.TextButton("Cancel", on_click=lambda: app.page.pop_dialog()),
                 ft.FilledButton("Save", on_click=lambda: app.run(save()))],
    ))


def move_dialog(app: "DocVaultApp", d: dict) -> None:
    def pick(cat_id: int):
        async def go():
            app.page.pop_dialog()
            await app.update(d["id"], category_id=cat_id)
        return lambda: app.run(go())

    tiles = [ft.ListTile(leading=ft.Icon(icon(c["icon"]), color=c["color"]), title=ft.Text(c["name"]),
                         trailing=ft.Icon(ft.Icons.CHECK) if c["id"] == d.get("category_id") else None,
                         on_click=pick(c["id"])) for c in app.cats]
    app.page.show_dialog(ft.AlertDialog(
        title=ft.Text("Move to category"),
        content=ft.Column(tiles, scroll=ft.ScrollMode.ALWAYS, tight=True, width=360, height=440),
        actions=[ft.TextButton("Cancel", on_click=lambda: app.page.pop_dialog())],
    ))


ICON_CHOICES = ["folder", "receipt_long", "account_balance", "shield", "request_quote", "shopping_bag", "work",
                "flight", "medical_services", "home", "school", "directions_car", "menu_book", "mail", "pets",
                "child_care", "savings", "sports_soccer", "description"]
COLOR_CHOICES = ["#607D8B", "#E64A19", "#2E7D32", "#1565C0", "#6A1B9A", "#F57C00", "#C62828", "#00897B", "#5E35B1"]


def category_dialog(app: "DocVaultApp", cat: dict | None = None) -> None:
    from api import ApiError, Offline

    name = ft.TextField(label="Name", value=cat["name"] if cat else "", autofocus=True)
    icon_dd = ft.Dropdown(label="Icon", value=cat["icon"] if cat else "folder", options=[
        ft.DropdownOption(key=i, text=i.replace("_", " "), leading_icon=icon(i))
        for i in dict.fromkeys(ICON_CHOICES + ([cat["icon"]] if cat else []))])
    color_dd = ft.Dropdown(label="Color", value=cat["color"] if cat else COLOR_CHOICES[0], options=[
        ft.DropdownOption(key=c, text=c, leading_icon=ft.Icon(ft.Icons.CIRCLE, color=c))
        for c in dict.fromkeys(COLOR_CHOICES + ([cat["color"]] if cat else []))])

    async def save():
        if not (name.value or "").strip():
            return
        try:
            if cat:
                await app.api.update_category(cat["id"], name=name.value.strip(), icon=icon_dd.value, color=color_dd.value)
            else:
                await app.api.create_category(name.value.strip(), icon_dd.value, color_dd.value)
        except (ApiError, Offline) as e:
            app.toast(str(e))
            return
        app.page.pop_dialog()
        await app.sync()

    async def delete():
        try:
            await app.api.delete_category(cat["id"])
        except (ApiError, Offline) as e:
            app.toast(str(e))
            return
        app.page.pop_dialog()
        app.toast(f"Deleted {cat['name']}; its documents moved to Other")
        await app.sync()

    actions = [ft.TextButton("Cancel", on_click=lambda: app.page.pop_dialog()),
               ft.FilledButton("Save", on_click=lambda: app.run(save()))]
    if cat and cat["name"] != "Other":
        actions.insert(0, ft.TextButton("Delete", on_click=lambda: app.run(delete())))
    app.page.show_dialog(ft.AlertDialog(title=ft.Text("Edit category" if cat else "New category"),
                                        content=ft.Column([name, icon_dd, color_dd], tight=True, width=340),
                                        actions=actions))


def empty_state(ic: ft.Icons, text: str) -> ft.Control:
    return ft.Container(padding=40, alignment=ft.Alignment.CENTER, content=ft.Column(
        [ft.Icon(ic, size=48, color=ft.Colors.OUTLINE),
         ft.Text(text, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER))
