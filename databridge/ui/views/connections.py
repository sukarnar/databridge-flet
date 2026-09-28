"""Connections: file systems and databases, with generated forms and a Test button."""

import flet as ft

from databridge.connectors.database import DIALECTS, installed_dialects
from databridge.connectors.registry import CONNECTORS
from databridge.core.security import decrypt_json
from databridge.services import connections as svc
from databridge.ui.common import mounted, ModelForm, card, chip, close_dialog, confirm, dialog, empty_state, guarded, page_header, toast


def _summary(conn) -> str:
    c = conn.config
    if conn.type == "database":
        where = c.get("host") or c.get("database") or "custom URL"
        return f"{c.get('dialect', '')} · {where}"
    return f"{c.get('protocol', 'file')} · {c.get('host') or ''}{c.get('root', '')} · {c.get('file_pattern', '*')}"


class ConnectionsView:
    def __init__(self, app):
        self.app = app
        self.page = app.page

    def build(self) -> ft.Control:
        conns = svc.list_connections()
        items: list[ft.Control] = []
        for c in conns:
            status = (chip("connected", ft.Colors.GREEN_600) if c.last_test_ok
                      else chip("failed", ft.Colors.RED_500) if c.last_test_ok is False else chip("not tested"))
            items.append(card(ft.Row([
                ft.Icon(ft.Icons.STORAGE if c.type == "database" else ft.Icons.FOLDER, color=ft.Colors.PRIMARY, size=30),
                ft.Column([
                    ft.Row([ft.Text(c.name, size=15, weight=ft.FontWeight.W_600), status], spacing=10),
                    ft.Text(_summary(c), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(c.last_test_message or "", size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True),
                ft.OutlinedButton("Test", icon=ft.Icons.BOLT, on_click=guarded(self.page, lambda _, i=c.id: self.test(i))),
                ft.OutlinedButton("Explore", icon=ft.Icons.ACCOUNT_TREE,
                                  on_click=lambda _, i=c.id: self.app.navigate("explorer", connection_id=i)),
                *([ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip="Edit", on_click=lambda _, cc=c: self.edit(cc)),
                   ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Delete", on_click=lambda _, cc=c: confirm(
                       self.page, "Delete connection", f"Delete {cc.name}? Sources that use it stop refreshing.",
                       lambda: self.delete(cc)))] if self.app.can("manage_connections") else []),
            ], spacing=10)))

        admin = self.app.can("manage_connections")
        body = ft.Column(items, spacing=10) if items else empty_state(
            ft.Icons.CABLE, "No connections yet",
            "Connect a shared folder, SFTP server, cloud bucket or database to browse and pull objects."
            + ("" if admin else " Ask an admin to add one."),
            ft.FilledButton("Add connection", icon=ft.Icons.ADD, on_click=lambda _: self.edit(None)) if admin else None)
        return ft.Column([
            page_header("Connections", "Where your data lives. Passwords are encrypted and never shown again."
                        + ("" if admin else " Only admins can add or change connections."),
                        [ft.FilledButton("New connection", icon=ft.Icons.ADD, on_click=lambda _: self.edit(None))]
                        if admin else []),
            body,
        ], spacing=18, scroll=ft.ScrollMode.AUTO, expand=True)

    def delete(self, conn) -> None:
        self.app.require("manage_connections")
        svc.delete_connection(conn.id)
        self.app.audit("connection.delete", conn.name)
        self.app.navigate("connections")

    def test(self, conn_id: int) -> None:
        self.app.require("use_connections")
        result = svc.test_connection(conn_id)
        toast(self.page, result.message, error=not result.ok)
        self.app.navigate("connections")

    def edit(self, conn) -> None:
        name = ft.TextField(label="Name *", value=conn.name if conn else "", dense=True, autofocus=True, width=470)
        type_dd = ft.Dropdown(
            label="Connection type", value=conn.type if conn else "filesystem", dense=True,
            options=[ft.DropdownOption(key=k, text=v.label) for k, v in CONNECTORS.items()],
            disabled=conn is not None, width=470,
        )
        form_holder = ft.Column(tight=True)
        hint = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, width=470)
        state: dict = {}

        def render_form(_=None):
            cls = CONNECTORS[type_dd.value]
            values = dict(conn.config) if conn else {}
            if conn:
                values.update({k: "" for k in decrypt_json(conn.secret)})
            state["form"] = ModelForm(cls.config_model, values, cls.secret_fields, on_change=update_hint)
            form_holder.controls = [state["form"].view()]
            if mounted(form_holder):  # the dialog is open: redraw now (type changed)
                form_holder.update()
            update_hint()

        def update_hint():
            if type_dd.value == "database":
                dialect = state["form"].controls["dialect"].value
                ok = installed_dialects().get(dialect, False)
                hint.value = ("Driver installed." if ok else
                              f"Driver not installed on the server: pip install {DIALECTS[dialect][2]}")
                hint.color = ft.Colors.GREEN_700 if ok else ft.Colors.AMBER_800
            else:
                hint.value = "For network shares, the server running DataBridge must be able to reach the host."
                hint.color = ft.Colors.ON_SURFACE_VARIANT
            if mounted(hint):
                hint.update()

        type_dd.on_select = render_form
        render_form()

        self.app.require("manage_connections")

        def save(test: bool):
            self.app.require("manage_connections")
            if not name.value.strip():
                raise ValueError("Give the connection a name")
            saved = svc.save_connection(name.value.strip(), type_dd.value, state["form"].values(),
                                        conn.id if conn else None)
            self.app.audit("connection.update" if conn else "connection.create", saved.name, saved.type)
            close_dialog(self.page)
            if test:
                self.test(saved.id)
            else:
                toast(self.page, f"Saved {saved.name}")
                self.app.navigate("connections")

        dialog(self.page, "Edit connection" if conn else "New connection",
               ft.Column([name, type_dd, form_holder, hint], spacing=12, scroll=ft.ScrollMode.AUTO),
               [ft.TextButton("Cancel", on_click=lambda _: close_dialog(self.page)),
                ft.OutlinedButton("Save", on_click=guarded(self.page, lambda _: save(False))),
                ft.FilledButton("Save and test", on_click=guarded(self.page, lambda _: save(True)))],
               width=520, height=520)
