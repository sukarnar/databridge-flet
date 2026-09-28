"""Admin: user accounts, roles, password resets, lockouts, sessions and the audit log."""

from datetime import datetime, timezone

import flet as ft

from databridge.core.auth import ROLES
from databridge.services import users as svc
from databridge.ui.common import chip, close_dialog, confirm, dialog, empty_state, guarded, page_header, toast

ROLE_COLORS = {"admin": ft.Colors.DEEP_PURPLE_400, "designer": ft.Colors.INDIGO_400, "viewer": ft.Colors.BLUE_GREY_400}


def _fmt(dt) -> str:
    if not dt:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _locked(u) -> bool:
    lu = u.locked_until
    if lu is None:
        return False
    if lu.tzinfo is None:
        lu = lu.replace(tzinfo=timezone.utc)
    return lu > datetime.now(timezone.utc)


class UsersView:
    def __init__(self, app, tab: int = 0):
        self.app = app
        self.page = app.page
        self.tab = tab

    def build(self) -> ft.Control:
        self.app.require("manage_users")
        new_btn = ft.FilledButton("New user", icon=ft.Icons.PERSON_ADD, on_click=lambda _: self.edit(None))
        tabs = ft.Row([
            ft.SegmentedButton(
                segments=[ft.Segment(value="0", label=ft.Text("Accounts"), icon=ft.Icon(ft.Icons.PEOPLE)),
                          ft.Segment(value="1", label=ft.Text("Audit log"), icon=ft.Icon(ft.Icons.POLICY))],
                selected=[str(self.tab)],
                on_change=lambda e: self.app.navigate("users", tab=int(e.control.selected[0])),
            ),
        ])
        body = self.accounts() if self.tab == 0 else self.audit_log()
        return ft.Column([
            page_header("Users", "Admins create accounts and assign roles. New accounts get a temporary password "
                        "that must be changed at first sign-in.", [new_btn]),
            tabs, body,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------ accounts

    def accounts(self) -> ft.Control:
        users = svc.list_users()
        rows = []
        for u in users:
            status = (chip("locked", ft.Colors.RED_500) if _locked(u) else
                      chip("active", ft.Colors.GREEN_600) if u.active else chip("disabled", ft.Colors.OUTLINE))
            me = u.id == self.app.user.id
            actions = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, items=[
                ft.PopupMenuItem(content=ft.Text("Edit"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _, uu=u: self.edit(uu)),
                ft.PopupMenuItem(content=ft.Text("Reset password"), icon=ft.Icons.LOCK_RESET,
                                 on_click=lambda _, uu=u: self.reset(uu)),
                ft.PopupMenuItem(content=ft.Text("Unlock"), icon=ft.Icons.LOCK_OPEN, disabled=not _locked(u),
                                 on_click=guarded(self.page, lambda _, uu=u: self.unlock(uu))),
                ft.PopupMenuItem(content=ft.Text("Sign out everywhere"), icon=ft.Icons.LOGOUT,
                                 on_click=guarded(self.page, lambda _, uu=u: self.revoke(uu))),
                ft.PopupMenuItem(content=ft.Text("Disable" if u.active else "Enable"),
                                 icon=ft.Icons.BLOCK if u.active else ft.Icons.CHECK_CIRCLE_OUTLINE, disabled=me,
                                 on_click=guarded(self.page, lambda _, uu=u: self.toggle(uu))),
                ft.PopupMenuItem(content=ft.Text("Delete"), icon=ft.Icons.DELETE_OUTLINE, disabled=me,
                                 on_click=lambda _, uu=u: confirm(
                                     self.page, "Delete user", f"Delete {uu.username}? Their audit history is kept.",
                                     lambda: self.delete(uu))),
            ])
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Column([
                    ft.Text(u.username + (" (you)" if me else ""), size=13, weight=ft.FontWeight.W_600),
                    ft.Text(" · ".join(x for x in (u.full_name, u.email) if x), size=11.5,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=0, tight=True)),
                ft.DataCell(chip(u.role, ROLE_COLORS.get(u.role, ft.Colors.OUTLINE))),
                ft.DataCell(status),
                ft.DataCell(ft.Text("must change password" if u.must_change_password else "", size=11.5,
                                    color=ft.Colors.AMBER_800)),
                ft.DataCell(ft.Text(_fmt(u.last_login_at), size=12)),
                ft.DataCell(ft.Text(f"{_fmt(u.created_at)} by {u.created_by or '?'}", size=12)),
                ft.DataCell(actions),
            ]))
        legend = ft.Column([ft.Row([chip(r, ROLE_COLORS[r]), ft.Text(d.split(": ", 1)[1], size=12)], spacing=8)
                            for r, d in ROLES.items()], spacing=6)
        return ft.Column([
            ft.DataTable(columns=[ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.W_600)) for h in
                                  ("User", "Role", "Status", "", "Last sign-in", "Created", "")],
                         rows=rows, data_row_min_height=48, data_row_max_height=56, column_spacing=22),
            ft.Divider(),
            ft.Text("Roles", size=13, weight=ft.FontWeight.W_600),
            legend,
        ], spacing=10)

    def edit(self, user) -> None:
        self.app.require("manage_users")
        username = ft.TextField(label="User name", value=user.username if user else "", dense=True,
                                disabled=user is not None, hint_text="e.g. jane.doe", autofocus=user is None)
        name = ft.TextField(label="Full name", value=user.full_name if user else "", dense=True)
        email = ft.TextField(label="Email", value=user.email if user else "", dense=True)
        start_role = user.role if user else "designer"
        role = ft.Dropdown(label="Role", value=start_role, dense=True, width=300,
                           helper_text=ROLES[start_role].split(": ", 1)[1],
                           options=[ft.DropdownOption(key=r, text=r.title()) for r in ROLES])

        def role_changed(_):
            role.helper_text = ROLES[role.value].split(": ", 1)[1]
            role.update()

        role.on_select = role_changed
        pw_mode = ft.RadioGroup(value="generate", content=ft.Column([
            ft.Radio(value="generate", label="Generate a temporary password (recommended)"),
            ft.Radio(value="set", label="Set a password now"),
        ], spacing=0), visible=user is None)
        pw = ft.TextField(label="Password", password=True, can_reveal_password=True, dense=True, visible=False)
        must_change = ft.Checkbox(label="Must change password at first sign-in", value=True, visible=user is None)

        def mode_changed(_):
            pw.visible = pw_mode.value == "set"
            pw.update()

        pw_mode.on_change = mode_changed

        def save(_):
            if user:
                svc.update_user(user.id, self.app.user.username, role=role.value, full_name=name.value or "",
                                email=email.value or "")
                close_dialog(self.page)
                toast(self.page, f"Saved {user.username}")
                self.app.navigate("users")
                return
            chosen = pw.value if pw_mode.value == "set" else None
            created, password = svc.create_user(username.value or "", role.value, self.app.user.username,
                                                full_name=name.value or "", email=email.value or "",
                                                password=chosen, must_change=bool(must_change.value))
            close_dialog(self.page)
            if chosen is None:
                self.show_password(created.username, password, "Account created")
            else:
                toast(self.page, f"Created {created.username}")
                self.app.navigate("users")

        dialog(self.page, f"Edit {user.username}" if user else "New user", ft.Column([
            username, name, email, role, pw_mode, pw, must_change,
        ], spacing=12, tight=True), [
            ft.TextButton("Cancel", on_click=lambda _: close_dialog(self.page)),
            ft.FilledButton("Save" if user else "Create user", on_click=guarded(self.page, save)),
        ], width=480)

    def show_password(self, username: str, password: str, title: str) -> None:
        async def copy(_):
            await ft.Clipboard().set(password)
            toast(self.page, "Copied")

        def done(_):
            close_dialog(self.page)
            self.app.navigate("users")

        dialog(self.page, title, ft.Column([
            ft.Text(f"Give {username} this temporary password through a secure channel. It is shown only once, "
                    "and they must choose their own password at first sign-in.", size=13),
            ft.Container(ft.Row([ft.Text(password, selectable=True, font_family="monospace", size=15, expand=True),
                                 ft.IconButton(ft.Icons.CONTENT_COPY, tooltip="Copy", on_click=copy)]),
                         bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, padding=10, border_radius=8),
        ], tight=True, spacing=10), [ft.FilledButton("Done", on_click=done)], width=480)

    def reset(self, user) -> None:
        def go():
            self.app.require("manage_users")
            pw = svc.reset_password(user.id, self.app.user.username)
            self.show_password(user.username, pw, "Password reset")

        confirm(self.page, "Reset password", f"Give {user.username} a new temporary password and sign them out "
                "of all devices?", go, danger=False)

    def unlock(self, user) -> None:
        self.app.require("manage_users")
        svc.unlock(user.id, self.app.user.username)
        toast(self.page, f"Unlocked {user.username}")
        self.app.navigate("users")

    def revoke(self, user) -> None:
        self.app.require("manage_users")
        n = svc.revoke_sessions(user.id, self.app.user.username)
        toast(self.page, f"Signed {user.username} out of {n} session(s)")
        if user.id == self.app.user.id:
            self.page.run_task(self.app.sign_out, "You signed yourself out everywhere.")

    def toggle(self, user) -> None:
        self.app.require("manage_users")
        svc.update_user(user.id, self.app.user.username, active=not user.active)
        toast(self.page, f"{'Disabled' if user.active else 'Enabled'} {user.username}")
        self.app.navigate("users")

    def delete(self, user) -> None:
        self.app.require("manage_users")
        svc.delete_user(user.id, self.app.user.id, self.app.user.username)
        toast(self.page, f"Deleted {user.username}")
        self.app.navigate("users")

    # ------------------------------------------------------------ audit

    def audit_log(self) -> ft.Control:
        self.app.require("view_audit")
        events = svc.recent_audit(300)
        if not events:
            return empty_state(ft.Icons.POLICY, "No events yet", "Sign-ins and changes will appear here.")
        colors = {"auth.login_failed": ft.Colors.RED_500, "auth.login_blocked": ft.Colors.RED_500,
                  "security.denied": ft.Colors.RED_500}
        rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(_fmt(e.at), size=12)),
            ft.DataCell(ft.Text(e.username or "-", size=12, weight=ft.FontWeight.W_500)),
            ft.DataCell(ft.Text(e.action, size=12, color=colors.get(e.action))),
            ft.DataCell(ft.Text(e.target, size=12, width=220, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=e.target or None)),
            ft.DataCell(ft.Text(e.detail, size=12, width=240, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                tooltip=e.detail or None)),
            ft.DataCell(ft.Text(e.ip, size=12)),
        ]) for e in events]
        return ft.Row([ft.DataTable(
            columns=[ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.W_600)) for h in
                     ("When", "User", "Action", "Target", "Detail", "IP")],
            rows=rows, data_row_min_height=34, data_row_max_height=38, column_spacing=18,
        )], scroll=ft.ScrollMode.AUTO)
