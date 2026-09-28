"""Sources: uploaded spreadsheets and connection-backed objects, with snapshots and drift."""

import asyncio

import flet as ft

from databridge.config import settings
from databridge.ingest.sheet_profile import SUPPORTED_EXT, SheetProfile
from databridge.services import sources as svc
from databridge.ui.common import (card, chip, close_dialog, confirm, df_table, dialog, empty_state, guarded,
                                  page_header, toast, type_badge)
from databridge.ui.components.profile_wizard import ProfileWizard

KIND_LABEL = {"upload": "Uploaded file", "file": "File on connection", "table": "Database table", "sql": "SQL query",
              "workflow": "AI workflow output"}


async def pick_file(page: ft.Page) -> tuple[str, bytes] | None:
    """Opens the browser file picker and returns (filename, bytes), or None if cancelled."""
    picker = ft.FilePicker()
    files = await picker.pick_files(
        dialog_title="Choose a file", allow_multiple=False, with_data=True,
        file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=[e.lstrip(".") for e in sorted(SUPPORTED_EXT)],
    )
    if not files:
        return None
    f = files[0]
    if f.size > settings.max_upload_mb * 1024 * 1024:
        toast(page, f"{f.name} is larger than {settings.max_upload_mb} MB", error=True)
        return None
    return f.name, f.bytes or b""


class SourcesView:
    def __init__(self, app):
        self.app = app
        self.page = app.page

    def classify(self, src) -> None:
        from databridge.ui.views.workflows import classify_dialog

        classify_dialog(self.page, self.app, src.id, on_done=lambda: self.app.navigate("sources"))

    def build(self) -> ft.Control:
        designer = self.app.can("design")
        items = []
        for s in svc.list_sources():
            snap = svc.latest_snapshot(s.id)
            drift = (snap.drift or {}) if snap else {}
            badges = [chip(KIND_LABEL.get(s.kind, s.kind))]
            if drift.get("changed"):
                badges.append(chip("schema changed", ft.Colors.AMBER_700))
            levels = list((s.classification or {}).values())
            if levels.count("pii"):
                badges.append(chip(f"PII: {levels.count('pii')} col", ft.Colors.AMBER_700))
            if levels.count("confidential"):
                badges.append(chip(f"confidential: {levels.count('confidential')} col", ft.Colors.RED_400))
            when = snap.created_at.strftime("%Y-%m-%d %H:%M") if snap else "never"
            primary = (ft.OutlinedButton("Upload new version", icon=ft.Icons.UPLOAD_FILE,
                                         on_click=lambda _, src=s: self.page.run_task(self.upload_version, src))
                       if s.kind == "upload" else
                       ft.OutlinedButton("Refresh", icon=ft.Icons.REFRESH,
                                         on_click=guarded(self.page, lambda _, src=s: self.refresh(src))))
            items.append(card(ft.Row([
                ft.Icon(ft.Icons.TABLE_CHART, color=ft.Colors.PRIMARY, size=30),
                ft.Column([
                    ft.Row([ft.Text(s.name, size=15, weight=ft.FontWeight.W_600), *badges], spacing=8),
                    ft.Text(f"{len(s.fields)} columns · {snap.row_count if snap else 0:,} rows · last data {when}"
                            + (f" · {snap.file_name}" if snap and snap.file_name else ""),
                            size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"Source id {s.id} (use in POST /api/v1/ingest/{s.id})" if s.kind == "upload" else
                            f"Source id {s.id} · written by AI workflow runs" if s.kind == "workflow" else
                            f"Source id {s.id} (use in POST /api/v1/sources/{s.id}/refresh)",
                            size=11, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ], spacing=2, expand=True),
                ft.OutlinedButton("View", icon=ft.Icons.VISIBILITY, on_click=guarded(self.page, lambda _, src=s: self.view(src))),
                *([*([primary] if s.kind != "workflow" else []),
                   ft.IconButton(ft.Icons.SHIELD_OUTLINED, tooltip="Classify columns for AI (PII, confidential)",
                                 on_click=lambda _, src=s: self.classify(src)),
                   ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Delete", on_click=lambda _, src=s: confirm(
                       self.page, "Delete source", f"Delete {src.name}? Mappings using it will stop working.",
                       lambda: self.delete(src)))] if designer else []),
            ], spacing=10)))
        upload_btn = ft.FilledButton("Upload spreadsheet", icon=ft.Icons.UPLOAD_FILE,
                                     on_click=lambda _: self.page.run_task(self.upload_new))
        body = ft.Column(items, spacing=10) if items else empty_state(
            ft.Icons.UPLOAD_FILE, "No sources yet",
            "Upload an Excel or CSV file. DataBridge finds the header row, skips title and total rows, "
            "and keeps leading zeros. You can also add tables and files from the Explorer.",
            upload_btn if designer else None)
        return ft.Column([
            page_header("Sources", "Data coming in. Every new file or refresh becomes a versioned snapshot.", [
                ft.OutlinedButton("From a connection", icon=ft.Icons.ACCOUNT_TREE,
                                  on_click=lambda _: self.app.navigate("explorer")),
                upload_btn] if designer else []),
            body,
        ], spacing=18, scroll=ft.ScrollMode.AUTO, expand=True)

    def delete(self, src) -> None:
        self.app.require("design")
        svc.delete_source(src.id)
        self.app.audit("source.delete", src.name)
        self.app.navigate("sources")

    async def upload_new(self):
        self.app.require("design")
        picked = await pick_file(self.page)
        if not picked:
            return
        name, content = picked

        def save(src_name: str, profile: SheetProfile):
            def work():
                self.app.require("design")
                src = svc.create_upload_source(src_name, name, content, profile)
                self.app.audit("source.create", src.name, name)
                toast(self.page, f"Imported {src.name}: {len(src.fields)} columns")
                self.app.navigate("sources")
            guarded(self.page, work)()

        await asyncio.to_thread(guarded(self.page, lambda: ProfileWizard(self.page, name, content, save).open()))

    async def upload_version(self, src):
        self.app.require("design")
        picked = await pick_file(self.page)
        if not picked:
            return
        name, content = picked

        def work():
            out = svc.ingest_file(src.id, name, content)
            self.app.audit("source.ingest", src.name, name)
            if out.get("skipped"):
                toast(self.page, "This exact file was already imported; nothing changed.")
            else:
                msg = f"Imported {out['rows']:,} rows."
                if out.get("drift") and out["drift"].get("changed"):
                    msg += " Schema changed: review the source."
                pubs = [p for p in out.get("published", []) if p["status"] == "published"]
                if pubs:
                    msg += " Republished: " + ", ".join(f"{p['mapping']} v{p['version']}" for p in pubs)
                toast(self.page, msg)
            self.app.navigate("sources")

        await asyncio.to_thread(guarded(self.page, work))

    def refresh(self, src) -> None:
        self.app.require("design")
        out = svc.refresh(src.id)
        self.app.audit("source.refresh", src.name)
        toast(self.page, f"Refreshed {src.name}: {out['rows']:,} rows")
        self.app.navigate("sources")

    def view(self, src) -> None:
        df = svc.load_snapshot(src.id, limit=100)
        snap = svc.latest_snapshot(src.id)
        drift = (snap.drift or {}) if snap else {}
        field_rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(f.get("column_letter", ""), size=12)),
            ft.DataCell(ft.Text(f["name"], size=12, weight=ft.FontWeight.W_500)),
            ft.DataCell(type_badge(f["type"])),
            ft.DataCell(ft.Text(f"{f.get('null_pct', 0)}%", size=12)),
            ft.DataCell(ft.Text(str(f.get("distinct", "")), size=12)),
            ft.DataCell(ft.Text(", ".join(str(x) for x in f.get("samples", [])[:3]), size=12, width=260,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)),
            ft.DataCell(ft.Text(f.get("note", ""), size=11, color=ft.Colors.AMBER_800)),
        ]) for f in src.fields]
        drift_text = []
        if drift.get("changed"):
            for k in ("added", "removed"):
                if drift.get(k):
                    drift_text.append(f"{k.title()}: {', '.join(drift[k])}")
            for r in drift.get("renamed", []):
                drift_text.append(f"Renamed: {r['from']} -> {r['to']}")
            for r in drift.get("retyped", []):
                drift_text.append(f"Type changed: {r['name']} {r['from']} -> {r['to']}")
        content = ft.Column([
            ft.Container(ft.Text("Schema drift in the latest file — " + "; ".join(drift_text), size=12),
                         bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER), padding=10,
                         border_radius=ft.BorderRadius.all(8), visible=bool(drift_text)),
            ft.Text("Columns", size=14, weight=ft.FontWeight.W_600),
            ft.DataTable(columns=[ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.W_600)) for h in
                                  ("Col", "Name", "Type", "Blank", "Distinct", "Samples", "Note")],
                         rows=field_rows, data_row_min_height=30, data_row_max_height=34, column_spacing=16),
            ft.Text(f"Data (first {df.height} rows)", size=14, weight=ft.FontWeight.W_600),
            df_table(df, max_rows=100, letters={f["name"]: f.get("column_letter", "") for f in src.fields}),
        ], spacing=10, scroll=ft.ScrollMode.AUTO)
        dialog(self.page, src.name, content, [ft.TextButton("Close", on_click=lambda _: close_dialog(self.page))],
               width=1000, height=600)
