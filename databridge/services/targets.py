"""Target schemas: from a template workbook, from a source's fields, or defined by hand."""

from typing import Any

from sqlalchemy import select

from databridge.core.db import session_scope
from databridge.core.models import TargetSchema
from databridge.core.types import CANONICAL_TYPES, base_type
from databridge.ingest.sheet_profile import parse_file


def list_targets() -> list[TargetSchema]:
    with session_scope() as s:
        return list(s.scalars(select(TargetSchema).order_by(TargetSchema.name)))


def get_target(target_id: int) -> TargetSchema:
    with session_scope() as s:
        t = s.get(TargetSchema, target_id)
        if not t:
            raise LookupError(f"Target schema {target_id} not found")
        return t


def _clean_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for f in fields:
        name = str(f.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        t = f.get("type") or "string"
        if base_type(t) not in CANONICAL_TYPES:
            t = "string"
        out.append({"name": name, "type": t, "required": bool(f.get("required")),
                    "description": f.get("description", "")})
    return out


def save_target(name: str, fields: list[dict[str, Any]], origin: str = "manual",
                target_id: int | None = None) -> TargetSchema:
    with session_scope() as s:
        t = s.get(TargetSchema, target_id) if target_id else TargetSchema(name=name, origin=origin)
        t.name, t.fields = name, _clean_fields(fields)
        s.add(t)
        s.flush()
        return t


def target_from_template(name: str, filename: str, content: bytes) -> TargetSchema:
    """Header row of a template workbook becomes the field list; types come from any sample rows."""
    result = parse_file(content, filename)
    fields = [{"name": f["name"], "type": f["type"] if f.get("distinct") else "string", "required": False}
              for f in result.fields]
    return save_target(name, fields, origin="template")


def delete_target(target_id: int) -> None:
    with session_scope() as s:
        t = s.get(TargetSchema, target_id)
        if t:
            s.delete(t)
