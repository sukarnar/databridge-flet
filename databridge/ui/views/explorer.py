"""Object Explorer: browse any connection lazily and add tables, views, sheets or SQL as sources."""

import json

import flet as ft

from databridge.connectors.base import Node
from databridge.ingest.sheet_profile import SPREADSHEET_EXT, ext_of
from databridge.services import connections as conn_svc
from databridge.services import sources as src_svc
from databridge.ui.common import (mounted, card, chip, close_dialog, df_table, dialog, empty_state, guarded, page_header,
                                  toast, type_badge)

ICONS = {"folder": ft.Icons.FOLDER, "file": ft.Icons.INSERT_DRIVE_FILE, "sheet": ft.Icons.GRID_ON,
         "schema": ft.Icons.SCHEMA, "table": ft.Icons.TABLE_ROWS, "view": ft.Icons.VIEW_LIST}


def _key(ref: dict) -> str:
    return json.dumps(ref, sort_keys=True)


class ExplorerView:
    def __init__(self, app, connection_id: int | None = None):
        self.app = app
        self.page = app.page
        self.conns = conn_svc.list_connections()
        self.conn_id = connection_id or (self.conns[0].id if self.conns else None)
        self.children: dict[str, list[Node]] = {}
        self.expanded: set[str] = set()
        self.selected: Node | None = None
        self.tree = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.detail = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    @property
    def conn(self):
        return next((c for c in self.conns if c.id == self.conn_id), None)

    def build(self) -> ft.Control:
        if not self.conns:
            return ft.Column([page_header("Explorer"), empty_state(
                ft.Icons.ACCOUNT_TREE, "No connections to explore",
                "Add a database or file system connection first.",
                ft.FilledButton("Add connection", on_click=lambda _: self.app.navigate("connections")))])
        picker = ft.Dropdown(
            label="Connection", value=str(self.conn_id), width=320, dense=True,
            options=[ft.DropdownOption(key=str(c.id), text=c.name) for c in self.conns],
            on_select=lambda e: self.app.navigate("explorer", connection_id=int(e.control.value)),
        )
        actions = [picker]
        if self.conn and self.conn.type == "database":
            actions.append(ft.OutlinedButton("Custom SQL", icon=ft.Icons.CODE, on_click=lambda _: self.show_sql()))
        guarded(self.page, self.load_root)()
        self.show_placeholder()
        return ft.Column([
            page_header("Explorer", "Browse schemas, tables, views, folders, files and sheets. "
                        "Select one to see its columns and data.", actions),
            ft.Row([
                ft.Container(card(self.tree, padding=8), width=360),
                ft.Container(card(self.detail), expand=True),
            ], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH, spacing=14),
        ], spacing=16, expand=True)

    # ------------------------------------------------------------ tree

    def load_root(self) -> None:
        self.children["root"] = conn_svc.browse(self.conn_id, None)
        self.render_tree()

    def render_tree(self) -> None:
        rows: list[ft.Control] = []

        def add(nodes: list[Node], depth: int):
            for n in nodes:
                k = _key(n.ref)
                is_open = k in self.expanded
                selected = self.selected is not None and _key(self.selected.ref) == k
                rows.append(ft.Container(
                    ft.Row([
                        ft.Container(width=depth * 16),
                        ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN if is_open else ft.Icons.KEYBOARD_ARROW_RIGHT,
                                size=18, opacity=1 if n.has_children else 0),
                        ft.Icon(ICONS.get(n.kind, ft.Icons.DESCRIPTION), size=18, color=ft.Colors.PRIMARY),
                        ft.Text(n.name, size=13, expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                weight=ft.FontWeight.W_600 if selected else None),
                        ft.Text(n.detail, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=4),
                    height=32, padding=ft.Padding.symmetric(horizontal=6), border_radius=ft.BorderRadius.all(6),
                    bgcolor=ft.Colors.SECONDARY_CONTAINER if selected else None,
                    on_click=guarded(self.page, lambda _, node=n: self.click(node)), ink=True,
                ))
                if is_open:
                    add(self.children.get(k, []), depth + 1)

        add(self.children.get("root", []), 0)
        self.tree.controls = rows or [ft.Text("Nothing here (check the file pattern or schema allowlist).",
                                              size=12, color=ft.Colors.ON_SURFACE_VARIANT)]
        if mounted(self.tree):
            self.tree.update()

    def click(self, node: Node) -> None:
        k = _key(node.ref)
        if node.has_children:
            if k in self.expanded:
                self.expanded.discard(k)
            else:
                if k not in self.children:
                    self.children[k] = conn_svc.browse(self.conn_id, node.ref)
                self.expanded.add(k)
        readable = node.kind in {"table", "view", "sheet"} or (
            node.kind == "file" and ext_of(node.ref.get("path", "")) not in SPREADSHEET_EXT)
        if readable:
            self.selected = node
            self.show_detail(node)
        self.render_tree()

    # ------------------------------------------------------------ detail

    def show_placeholder(self) -> None:
        self.detail.controls = [empty_state(ft.Icons.TOUCH_APP, "Select an object",
                                            "Expand the tree on the left and pick a table, view or sheet.")]

    def show_detail(self, node: Node, ref: dict | None = None) -> None:
        ref = ref or node.ref
        self.detail.controls = [ft.ProgressRing()]
        self.detail.update()
        fields = conn_svc.describe(self.conn_id, ref)
        df = conn_svc.preview(self.conn_id, ref, 100)
        field_rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(f["name"], size=12, weight=ft.FontWeight.W_500)),
            ft.DataCell(type_badge(f["type"])),
            ft.DataCell(ft.Text(f.get("native_type", ""), size=11, color=ft.Colors.ON_SURFACE_VARIANT)),
            ft.DataCell(ft.Row(([chip("PK", ft.Colors.PRIMARY)] if f.get("pk") else [])
                               + ([chip(f"FK: {f['fk']}", ft.Colors.TEAL_600)] if f.get("fk") else []), spacing=4)),
            ft.DataCell(ft.Text("yes" if f.get("nullable", True) else "no", size=12)),
        ]) for f in fields]
        title = ref.get("sql", "")[:60] + "…" if ref.get("sql") else node.name
        default_name = node.name if not ref.get("sql") else "Custom query"
        self.detail.controls = [
            ft.Row([
                ft.Icon(ICONS.get(node.kind, ft.Icons.CODE), color=ft.Colors.PRIMARY),
                ft.Text(title, size=18, weight=ft.FontWeight.W_600, expand=True),
                ft.FilledButton("Add as source", icon=ft.Icons.ADD, visible=self.app.can("design"),
                                on_click=lambda _: self.add_source(default_name, ref)),
            ]),
            ft.Text(f"{len(fields)} columns · showing first {df.height} rows", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT),
            ft.DataTable(columns=[ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.W_600))
                                  for h in ("Column", "Type", "Native type", "Keys", "Nullable")],
                         rows=field_rows, data_row_min_height=32, data_row_max_height=36, column_spacing=18),
            ft.Text("Preview", size=14, weight=ft.FontWeight.W_600),
            df_table(df, max_rows=100),
        ]
        self.detail.update()

    def add_source(self, default_name: str, ref: dict) -> None:
        name = ft.TextField(label="Source name", value=f"{self.conn.name} · {default_name}", autofocus=True)

        def save(_):
            self.app.require("design")
            src = src_svc.create_connector_source(name.value.strip(), self.conn_id, ref)
            self.app.audit("source.create", src.name, f"from connection {self.conn.name}")
            close_dialog(self.page)
            toast(self.page, f"Added {src.name} with {len(src.fields)} columns")
            self.app.navigate("sources")

        dialog(self.page, "Add as source", ft.Column([
            name,
            ft.Text("DataBridge takes a snapshot now. Refresh it later from Sources, on a schedule, "
                    "or by calling POST /api/v1/sources/{id}/refresh.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ], tight=True, spacing=10), [
            ft.TextButton("Cancel", on_click=lambda _: close_dialog(self.page)),
            ft.FilledButton("Add source", on_click=guarded(self.page, save)),
        ], width=460)

    def show_sql(self) -> None:
        sql = ft.TextField(label="SELECT query", multiline=True, min_lines=8, max_lines=16,
                           text_style=ft.TextStyle(font_family="monospace", size=13),
                           hint_text="SELECT o.order_id, c.name, o.amount\nFROM orders o JOIN customers c ON c.id = o.customer_id")
        msg = ft.Text("Only a single read-only SELECT is allowed.", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        def run(_):
            connector = conn_svc.connector_for(self.conn_id)
            try:
                connector.validate_sql(sql.value or "")  # type: ignore[attr-defined]
            finally:
                connector.close()
            close_dialog(self.page)
            node = Node("Custom query", "view", {"sql": sql.value})
            self.selected = None
            self.show_detail(node, {"sql": sql.value})

        dialog(self.page, "Custom SQL", ft.Column([sql, msg], tight=True, spacing=8), [
            ft.TextButton("Cancel", on_click=lambda _: close_dialog(self.page)),
            ft.FilledButton("Validate and preview", on_click=guarded(self.page, run)),
        ], width=640)
