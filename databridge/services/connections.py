"""Connection management: create, update, test, browse."""

from typing import Any

from sqlalchemy import select

from databridge.connectors.base import Connector, Node, TestResult, split_config
from databridge.connectors.registry import build_connector, connector_class
from databridge.core.db import session_scope
from databridge.core.models import Connection
from databridge.core.security import decrypt_json, encrypt_json


def list_connections() -> list[Connection]:
    with session_scope() as s:
        return list(s.scalars(select(Connection).order_by(Connection.name)))


def get_connection(conn_id: int) -> Connection:
    with session_scope() as s:
        conn = s.get(Connection, conn_id)
        if not conn:
            raise LookupError(f"Connection {conn_id} not found")
        return conn


def save_connection(name: str, type_name: str, values: dict[str, Any], conn_id: int | None = None) -> Connection:
    """Creates or updates a connection. Blank secret fields keep the stored secret."""
    cls = connector_class(type_name)
    cls.config_model(**values)  # validate before saving
    plain, secret = split_config(cls, values)
    with session_scope() as s:
        conn = s.get(Connection, conn_id) if conn_id else Connection(name=name, type=type_name)
        if conn_id and not conn:
            raise LookupError(f"Connection {conn_id} not found")
        existing = decrypt_json(conn.secret) if conn_id else {}
        merged = {**existing, **{k: v for k, v in secret.items() if v not in (None, "")}}
        conn.name, conn.type, conn.config, conn.secret = name, type_name, plain, encrypt_json(merged)
        s.add(conn)
        s.flush()
        return conn


def delete_connection(conn_id: int) -> None:
    with session_scope() as s:
        conn = s.get(Connection, conn_id)
        if conn:
            s.delete(conn)


def connector_for(conn_id: int) -> Connector:
    conn = get_connection(conn_id)
    return build_connector(conn.type, conn.config, conn.secret)


def test_connection(conn_id: int) -> TestResult:
    connector = connector_for(conn_id)
    try:
        result = connector.test()
    finally:
        connector.close()
    with session_scope() as s:
        conn = s.get(Connection, conn_id)
        conn.last_test_ok, conn.last_test_message = result.ok, result.message
    return result


def browse(conn_id: int, ref: dict[str, Any] | None = None) -> list[Node]:
    connector = connector_for(conn_id)
    try:
        return connector.browse(ref)
    finally:
        connector.close()


def describe(conn_id: int, ref: dict[str, Any]) -> list[dict[str, Any]]:
    connector = connector_for(conn_id)
    try:
        return connector.describe(ref)
    finally:
        connector.close()


def preview(conn_id: int, ref: dict[str, Any], limit: int = 100):
    connector = connector_for(conn_id)
    try:
        return connector.preview(ref, limit)
    finally:
        connector.close()
