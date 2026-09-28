"""Source objects and snapshots: uploads, files on shares, database tables and SQL queries."""

import hashlib
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import select

from databridge.config import settings
from databridge.core.db import session_scope
from databridge.core.models import Snapshot, SourceObject
from databridge.ingest.profiling import detect_drift, profile_fields
from databridge.ingest.sheet_profile import SheetProfile, parse_file
from databridge.services import connections as conn_svc
from databridge.services.runs import track


def list_sources() -> list[SourceObject]:
    with session_scope() as s:
        return list(s.scalars(select(SourceObject).order_by(SourceObject.name)))


def get_source(source_id: int) -> SourceObject:
    with session_scope() as s:
        src = s.get(SourceObject, source_id)
        if not src:
            raise LookupError(f"Source {source_id} not found")
        return src


def delete_source(source_id: int) -> None:
    with session_scope() as s:
        src = s.get(SourceObject, source_id)
        if src:
            s.delete(src)


def latest_snapshot(source_id: int) -> Snapshot | None:
    with session_scope() as s:
        return s.scalars(
            select(Snapshot).where(Snapshot.source_id == source_id).order_by(Snapshot.id.desc()).limit(1)
        ).first()


def list_snapshots(source_id: int) -> list[Snapshot]:
    with session_scope() as s:
        return list(s.scalars(select(Snapshot).where(Snapshot.source_id == source_id).order_by(Snapshot.id.desc())))


def load_snapshot(source_id: int, limit: int | None = None) -> pl.DataFrame:
    snap = latest_snapshot(source_id)
    if not snap:
        raise LookupError("Source has no data yet")
    lf = pl.scan_parquet(snap.parquet_path)
    return (lf.head(limit) if limit else lf).collect()


def _write_snapshot(source: SourceObject, df: pl.DataFrame, fields: list[dict[str, Any]],
                    file_name: str | None, file_hash: str | None, notes: list[str]) -> Snapshot:
    folder = settings.data_dir / "snapshots" / str(source.id)
    folder.mkdir(parents=True, exist_ok=True)
    with session_scope() as s:
        src = s.get(SourceObject, source.id)
        drift = detect_drift(src.fields, fields) if src.fields else None
        snap = Snapshot(source_id=src.id, file_name=file_name, file_hash=file_hash,
                        row_count=df.height, parquet_path="", notes=notes, drift=drift)
        s.add(snap)
        s.flush()
        path = folder / f"{snap.id}.parquet"
        df.write_parquet(path)
        snap.parquet_path = str(path.resolve())
        src.fields = fields
        src.latest_snapshot_id = snap.id
        return snap


def _find_by_hash(source_id: int, file_hash: str) -> Snapshot | None:
    with session_scope() as s:
        return s.scalars(select(Snapshot).where(Snapshot.source_id == source_id,
                                                Snapshot.file_hash == file_hash)).first()


# ------------------------------------------------------------------ uploads / files


def create_upload_source(name: str, filename: str, content: bytes, profile: SheetProfile) -> SourceObject:
    """First upload: saves the Sheet Profile with the source and ingests the file."""
    with session_scope() as s:
        src = SourceObject(name=name, kind="upload", object_ref={"file_name": filename},
                           sheet_profile=profile.to_dict(), fields=[])
        s.add(src)
        s.flush()
    ingest_file(src.id, filename, content, auto_publish=False)
    return get_source(src.id)


def ingest_file(source_id: int, filename: str, content: bytes, auto_publish: bool = True) -> dict[str, Any]:
    """Parses a new file with the source's saved profile, stores a snapshot and republishes mappings.

    Returns {snapshot_id, rows, drift, skipped, published: [...]}.
    """
    src = get_source(source_id)
    file_hash = hashlib.sha256(content).hexdigest()
    existing = _find_by_hash(source_id, file_hash)
    if existing:
        return {"snapshot_id": existing.id, "rows": existing.row_count, "skipped": True,
                "message": "Identical file already ingested", "drift": None, "published": []}
    upload_dir = settings.data_dir / "uploads" / str(source_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / f"{file_hash[:12]}_{Path(filename).name}").write_bytes(content)

    with track("ingest", f"{src.name} <- {filename}") as run:
        result = parse_file(content, filename, SheetProfile.from_dict(src.sheet_profile))
        snap = _write_snapshot(src, result.df, result.fields, filename, file_hash, result.notes)
        run.rows_in = run.rows_out = result.df.height
        drift = snap.drift or {}
        if drift.get("changed"):
            run.status = "warning"
            run.message = _drift_text(drift)
    published = _auto_publish(source_id, drift) if auto_publish else []
    return {"snapshot_id": snap.id, "rows": snap.row_count, "skipped": False, "drift": snap.drift,
            "notes": result.notes, "published": published}


def _drift_text(drift: dict[str, Any]) -> str:
    parts = []
    if drift.get("added"):
        parts.append("added " + ", ".join(drift["added"]))
    if drift.get("removed"):
        parts.append("removed " + ", ".join(drift["removed"]))
    if drift.get("renamed"):
        parts.append("renamed " + ", ".join(f"{r['from']}->{r['to']}" for r in drift["renamed"]))
    if drift.get("retyped"):
        parts.append("retyped " + ", ".join(f"{r['name']} {r['from']}->{r['to']}" for r in drift["retyped"]))
    return "Schema drift: " + "; ".join(parts)


def _auto_publish(source_id: int, drift: dict[str, Any]) -> list[dict[str, Any]]:
    from databridge.services import mappings as map_svc

    out = []
    for m in map_svc.mappings_for_source(source_id):
        if not (m.status == "published" and m.auto_publish):
            continue
        missing = [c for c in map_svc.referenced_source_columns(m) if c in set(drift.get("removed") or [])]
        if missing:
            out.append({"mapping": m.name, "status": "paused", "reason": f"mapped columns missing: {missing}"})
            continue
        ds = map_svc.publish(m.id, use_published_spec=True)
        out.append({"mapping": m.name, "status": "published", "version": ds.version, "rows": ds.row_count,
                    "rejected": ds.rejected_count, "run_id": ds.run_id})
    return out


def update_profile(source_id: int, profile: SheetProfile) -> None:
    with session_scope() as s:
        src = s.get(SourceObject, source_id)
        src.sheet_profile = profile.to_dict()


# ------------------------------------------------------------------ connector-backed sources


def create_connector_source(name: str, connection_id: int, ref: dict[str, Any],
                            profile: SheetProfile | None = None) -> SourceObject:
    """A table, view, SQL query, or a file on a connected file system."""
    conn = conn_svc.get_connection(connection_id)
    if conn.type == "database":
        kind = "sql" if ref.get("sql") else "table"
    else:
        kind = "file"
    with session_scope() as s:
        src = SourceObject(name=name, kind=kind, connection_id=connection_id, object_ref=ref,
                           sheet_profile=profile.to_dict() if profile else None, fields=[])
        s.add(src)
        s.flush()
    refresh(src.id, auto_publish=False)
    return get_source(src.id)


def refresh(source_id: int, auto_publish: bool = True) -> dict[str, Any]:
    """Pulls fresh data from the source's connection into a new snapshot."""
    src = get_source(source_id)
    if src.kind == "upload" or not src.connection_id:
        raise ValueError("Uploaded sources refresh by uploading a new file (POST /api/v1/ingest/{source_id})")
    connector = conn_svc.connector_for(src.connection_id)
    try:
        if src.kind == "file":
            content = connector.read_bytes(src.object_ref)  # type: ignore[attr-defined]
            profile = SheetProfile.from_dict(src.sheet_profile) if src.sheet_profile else None
            if profile is None and src.object_ref.get("sheet"):
                profile = SheetProfile(sheet=src.object_ref["sheet"])
                from databridge.ingest.sheet_profile import suggest_profile

                profile = suggest_profile(content, src.object_ref["path"], src.object_ref["sheet"])
                update_profile(source_id, profile)
            connector.close()
            return ingest_file(source_id, src.object_ref["path"].split("/")[-1], content, auto_publish)

        with track("extract", src.name) as run:
            frames = list(connector.read(src.object_ref))
            df = pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()
            fields = profile_fields(df)
            snap = _write_snapshot(src, df, fields, None, None, [])
            run.rows_in = run.rows_out = df.height
            if snap.drift and snap.drift.get("changed"):
                run.status, run.message = "warning", _drift_text(snap.drift)
    finally:
        connector.close()
    published = _auto_publish(source_id, snap.drift or {}) if auto_publish else []
    return {"snapshot_id": snap.id, "rows": snap.row_count, "drift": snap.drift, "published": published}


# ------------------------------------------------------------------ data classification (AI egress rules)


def set_classification(source_id: int, classification: dict[str, str], actor: str) -> None:
    """Saves {column: public | internal | pii | confidential}; "internal" (the default) is not stored."""
    from databridge.ai.guardrails import LEVELS
    from databridge.services.users import audit

    clean = {c: lvl for c, lvl in classification.items() if lvl in LEVELS and lvl != "internal"}
    with session_scope() as s:
        src = s.get(SourceObject, source_id)
        if not src:
            raise LookupError(f"Source {source_id} not found")
        src.classification = clean or None
        name = src.name
    audit(actor, "source.classify", name, ", ".join(f"{c}={lvl}" for c, lvl in sorted(clean.items())) or "cleared")
