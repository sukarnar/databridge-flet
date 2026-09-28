"""Shared UI helpers: notifications, dialogs, tables, badges and generated forms."""

import traceback
from collections.abc import Callable
from typing import Any, get_args, get_origin

import flet as ft
import polars as pl
from pydantic import BaseModel

from databridge.core.types import CANONICAL_TYPES, base_type

TYPE_COLORS = {
    "string": ft.Colors.BLUE_GREY_400,
    "integer": ft.Colors.INDIGO_400,
    "decimal": ft.Colors.INDIGO_400,
    "float": ft.Colors.INDIGO_400,
    "boolean": ft.Colors.TEAL_400,
    "date": ft.Colors.DEEP_ORANGE_400,
    "timestamp": ft.Colors.DEEP_ORANGE_400,
    "json": ft.Colors.PURPLE_400,
    "binary": ft.Colors.BROWN_400,
}
STATUS_COLORS = {
    "ok": ft.Colors.GREEN_600,
    "lossy": ft.Colors.AMBER_700,
    "incompatible": ft.Colors.RED_500,
    "error": ft.Colors.RED_500,
    "suggested": ft.Colors.PRIMARY,
    "unmapped": ft.Colors.OUTLINE,
}
RUN_COLORS = {"ok": ft.Colors.GREEN_600, "warning": ft.Colors.AMBER_700, "failed": ft.Colors.RED_500,
              "running": ft.Colors.BLUE_400}


def mounted(control: ft.Control) -> bool:
    """True once a control is on the page (Flet 1.0 raises instead of returning None)."""
    try:
        return control.page is not None
    except RuntimeError:
        return False


def toast(page: ft.Page, message: str, error: bool = False) -> None:
    page.show_dialog(ft.SnackBar(
        ft.Text(message, color=ft.Colors.ON_ERROR if error else None),
        bgcolor=ft.Colors.ERROR if error else None,
        duration=ft.Duration(seconds=6 if error else 3),
    ))


def guarded(page: ft.Page, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wraps an event handler so any exception shows as a red snackbar instead of failing silently."""

    def handler(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - user-facing boundary
            traceback.print_exc()
            toast(page, f"{type(e).__name__}: {e}", error=True)

    return handler


def close_dialog(page: ft.Page) -> None:
    page.pop_dialog()


def dialog(page: ft.Page, title: str, content: ft.Control, actions: list[ft.Control],
           width: int = 560, height: int | None = None) -> ft.AlertDialog:
    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(title, weight=ft.FontWeight.W_600),
        content=ft.Container(content, width=width, height=height, padding=ft.Padding.only(top=8)),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)
    return dlg


def confirm(page: ft.Page, title: str, message: str, on_yes: Callable[[], None], danger: bool = True) -> None:
    def yes(_):
        close_dialog(page)
        guarded(page, on_yes)()

    dialog(page, title, ft.Text(message), [
        ft.TextButton("Cancel", on_click=lambda _: close_dialog(page)),
        ft.FilledButton("Delete" if danger else "OK", on_click=yes,
                        style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR) if danger else None),
    ], width=420)


def type_badge(ctype: str) -> ft.Control:
    color = TYPE_COLORS.get(base_type(ctype), ft.Colors.OUTLINE)
    return ft.Container(
        ft.Text(ctype, size=10.5, color=color, weight=ft.FontWeight.W_500, no_wrap=True),
        padding=ft.Padding.symmetric(horizontal=6, vertical=1),
        border=ft.Border.all(1, color),
        border_radius=ft.BorderRadius.all(10),
    )


def chip(text: str, color: str = ft.Colors.OUTLINE, filled: bool = False) -> ft.Control:
    return ft.Container(
        ft.Text(text, size=11, color=ft.Colors.ON_PRIMARY if filled else color, weight=ft.FontWeight.W_500),
        bgcolor=color if filled else None,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        border=None if filled else ft.Border.all(1, color),
        border_radius=ft.BorderRadius.all(12),
    )


def page_header(title: str, subtitle: str = "", actions: list[ft.Control] | None = None) -> ft.Control:
    return ft.Row(
        [
            ft.Column([
                ft.Text(title, size=22, weight=ft.FontWeight.W_600),
                ft.Text(subtitle, size=13, color=ft.Colors.ON_SURFACE_VARIANT) if subtitle else ft.Container(),
            ], spacing=2, expand=True),
            ft.Row(actions or [], spacing=8),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def empty_state(icon: ft.IconData, title: str, message: str, action: ft.Control | None = None) -> ft.Control:
    return ft.Container(
        ft.Column([
            ft.Icon(icon, size=44, color=ft.Colors.OUTLINE),
            ft.Text(title, size=16, weight=ft.FontWeight.W_600),
            ft.Text(message, size=13, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            action or ft.Container(),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        padding=40,
        alignment=ft.Alignment.CENTER,
    )


def card(content: ft.Control, padding: int = 16, expand: bool | int = False) -> ft.Control:
    return ft.Container(
        content,
        padding=padding,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=ft.BorderRadius.all(10),
        bgcolor=ft.Colors.SURFACE,
        expand=expand,
    )


def _cell_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


def df_table(df: pl.DataFrame, cell_errors: dict[int, dict[str, str]] | None = None,
             max_rows: int = 50, highlight_cols: set[str] | None = None,
             letters: dict[str, str] | None = None) -> ft.Control:
    """Spreadsheet-like grid. cell_errors = {row_idx: {column: message}} marks cells red with a tooltip."""
    if df.width == 0:
        return ft.Text("No columns", color=ft.Colors.ON_SURFACE_VARIANT)
    cell_errors = cell_errors or {}
    cols = [c for c in df.columns if not c.startswith("__")]
    columns = [ft.DataColumn(ft.Text("#", size=11, color=ft.Colors.ON_SURFACE_VARIANT))]
    for c in cols:
        label = f"{letters[c]} · {c}" if letters and c in letters else c
        columns.append(ft.DataColumn(ft.Text(label, size=12, weight=ft.FontWeight.W_600,
                                             color=ft.Colors.PRIMARY if highlight_cols and c in highlight_cols else None)))
    rows = []
    for i, row in enumerate(df.head(max_rows).iter_rows(named=True)):
        errs = cell_errors.get(i, {})
        cells = [ft.DataCell(ft.Text(str(row.get("__row", i + 1)), size=11, color=ft.Colors.ON_SURFACE_VARIANT))]
        for c in cols:
            text = ft.Text(_cell_text(row[c]), size=12, no_wrap=True, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, width=180,
                           color=ft.Colors.RED_600 if c in errs else None,
                           tooltip=errs.get(c))
            cells.append(ft.DataCell(ft.Container(
                text, bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.RED) if c in errs else None,
                padding=ft.Padding.symmetric(horizontal=4))))
        rows.append(ft.DataRow(cells=cells))
    table = ft.DataTable(
        columns=columns, rows=rows, column_spacing=18, data_row_min_height=32, data_row_max_height=32,
        heading_row_height=36, horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )
    return ft.Row([table], scroll=ft.ScrollMode.AUTO)


def type_dropdown(value: str = "string", label: str = "Type", width: int = 150,
                  on_select=None) -> ft.Dropdown:
    opts = CANONICAL_TYPES[:2] + ["decimal(12,2)", "decimal(18,4)"] + CANONICAL_TYPES[3:]
    if value not in opts:
        opts.insert(0, value)
    return ft.Dropdown(label=label, value=value, width=width, dense=True,
                       options=[ft.DropdownOption(key=o, text=o) for o in opts], on_select=on_select)


# ------------------------------------------------------------------ pydantic -> form


FORM_W = 470


class ModelForm:
    """Builds form controls from a Pydantic model; secret fields become password inputs."""

    def __init__(self, model: type[BaseModel], values: dict[str, Any] | None = None,
                 secret_fields: set[str] | None = None, on_change: Callable[[], None] | None = None):
        self.model = model
        self.secret_fields = secret_fields or set()
        self.controls: dict[str, ft.Control] = {}
        values = values or {}
        for name, f in model.model_fields.items():
            label = name.replace("_", " ").capitalize().replace("Url", "URL").replace("Json", "JSON")
            helper = f.description or None
            default = None if f.is_required() else f.default
            current = values.get(name, default)
            ann = f.annotation
            choices = get_args(ann) if get_origin(ann) is not None and str(get_origin(ann)).endswith("Literal") else None
            if choices:
                ctl: ft.Control = ft.Dropdown(label=label, value=str(current or choices[0]), dense=True, width=FORM_W,
                                              helper_text=helper,
                                              options=[ft.DropdownOption(key=str(c), text=str(c)) for c in choices],
                                              on_select=(lambda _: on_change()) if on_change else None)
            else:
                is_secret = name in self.secret_fields
                ctl = ft.TextField(
                    label=label + (" (blank keeps the saved value)" if is_secret and values else "")
                    + (" *" if f.is_required() else ""),
                    value="" if is_secret else ("" if current in (None, "") else str(current)),
                    password=is_secret, can_reveal_password=is_secret, dense=True, width=FORM_W,
                    helper=helper,
                    keyboard_type=ft.KeyboardType.NUMBER if ann in (int, int | None) else None,
                )
            self.controls[name] = ctl

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, ctl in self.controls.items():
            v = ctl.value
            if v in (None, ""):
                continue
            f = self.model.model_fields[name]
            if f.annotation in (int, int | None):
                v = int(v)
            out[name] = v
        return out

    def view(self) -> ft.Control:
        return ft.Column(list(self.controls.values()), spacing=10, tight=True)
