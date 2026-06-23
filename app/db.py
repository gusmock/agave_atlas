from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .auth import hash_password, verify_password
from .config import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.resolved_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterable[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    sheet_name TEXT,
    header_row INTEGER,
    data_start_row INTEGER,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id INTEGER,
    sheet_name TEXT NOT NULL,
    column_index INTEGER NOT NULL,
    letter TEXT NOT NULL,
    header TEXT,
    group_name TEXT,
    subgroup_name TEXT,
    slug TEXT NOT NULL,
    UNIQUE(import_run_id, sheet_name, column_index),
    FOREIGN KEY(import_run_id) REFERENCES import_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id INTEGER,
    document_type TEXT NOT NULL DEFAULT 'patente',
    primary_identifier TEXT,
    title TEXT,
    abstract TEXT,
    claims TEXT,
    invention_description TEXT,
    publication_numbers TEXT,
    publication_dates TEXT,
    priority_date TEXT,
    inventors TEXT,
    assignees TEXT,
    cpc TEXT,
    ipc TEXT,
    family_legal_status TEXT,
    legal_status TEXT,
    family_legal_state TEXT,
    legal_state TEXT,
    relevant TEXT,
    office TEXT,
    application_year TEXT,
    source_filename TEXT,
    stored_filename TEXT,
    stored_path TEXT,
    file_sha256 TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'imported',
    extraction_message TEXT,
    extracted_json TEXT,
    raw_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(import_run_id) REFERENCES import_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS document_field_values (
    document_id INTEGER NOT NULL,
    source_column_id INTEGER NOT NULL,
    value TEXT,
    PRIMARY KEY(document_id, source_column_id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(source_column_id) REFERENCES source_columns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS document_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    subgroup_name TEXT,
    field_label TEXT,
    value_text TEXT,
    flag_value INTEGER NOT NULL DEFAULT 0,
    source_column_id INTEGER,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(source_column_id) REFERENCES source_columns(id) ON DELETE SET NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    abstract,
    claims,
    invention_description,
    publication_numbers,
    inventors,
    assignees,
    cpc,
    ipc,
    content='documents',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, abstract, claims, invention_description,
                              publication_numbers, inventors, assignees, cpc, ipc)
    VALUES (new.id, new.title, new.abstract, new.claims, new.invention_description,
            new.publication_numbers, new.inventors, new.assignees, new.cpc, new.ipc);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, abstract, claims,
                              invention_description, publication_numbers, inventors,
                              assignees, cpc, ipc)
    VALUES('delete', old.id, old.title, old.abstract, old.claims,
           old.invention_description, old.publication_numbers, old.inventors,
           old.assignees, old.cpc, old.ipc);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, abstract, claims,
                              invention_description, publication_numbers, inventors,
                              assignees, cpc, ipc)
    VALUES('delete', old.id, old.title, old.abstract, old.claims,
           old.invention_description, old.publication_numbers, old.inventors,
           old.assignees, old.cpc, old.ipc);
    INSERT INTO documents_fts(rowid, title, abstract, claims, invention_description,
                              publication_numbers, inventors, assignees, cpc, ipc)
    VALUES (new.id, new.title, new.abstract, new.claims, new.invention_description,
            new.publication_numbers, new.inventors, new.assignees, new.cpc, new.ipc);
END;

CREATE INDEX IF NOT EXISTS idx_documents_year ON documents(application_year);
CREATE INDEX IF NOT EXISTS idx_documents_office ON documents(office);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(family_legal_status);
CREATE INDEX IF NOT EXISTS idx_categories_group ON document_categories(group_name);
"""


DOCUMENT_FIELDS = {
    "Publication numbers": "publication_numbers",
    "Publication dates": "publication_dates",
    "Earliest priority date": "priority_date",
    "Title": "title",
    "Abstract": "abstract",
    "Claims": "claims",
    "Descrição da invenção": "invention_description",
    "Inventors": "inventors",
    "Latest standardized assignees - inventors removed": "assignees",
    "CPC - Cooperative classification": "cpc",
    "IPC - International classification": "ipc",
    "Family legal status": "family_legal_status",
    "Legal status (Pending, Granted, Revoked, Expired, Lapsed)": "legal_status",
    "Family legal state": "family_legal_state",
    "Legal state (Alive, Dead)": "legal_state",
    "Relevante?": "relevant",
    "Escritório": "office",
    "Ano de aplicação": "application_year",
}


OFFICE_LOCATIONS = {
    "BR": {"name": "Brasil", "city": "Brasília", "lat": -14.2350, "lon": -51.9253},
    "CN": {"name": "China", "city": "Pequim", "lat": 35.8617, "lon": 104.1954},
    "EP": {"name": "Escritório Europeu de Patentes", "city": "Munique", "lat": 48.1351, "lon": 11.5820},
    "IN": {"name": "Índia", "city": "Nova Délhi", "lat": 20.5937, "lon": 78.9629},
    "TW": {"name": "Taiwan", "city": "Taipei", "lat": 23.6978, "lon": 120.9605},
    "US": {"name": "Estados Unidos", "city": "Washington, DC", "lat": 37.0902, "lon": -95.7129},
    "WO": {"name": "WIPO / PCT", "city": "Genebra", "lat": 46.2044, "lon": 6.1432},
}


STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "according",
    "also",
    "among",
    "and",
    "another",
    "apenas",
    "apos",
    "aquele",
    "aquela",
    "aqueles",
    "aquelas",
    "aqui",
    "area",
    "areas",
    "around",
    "assim",
    "base",
    "based",
    "been",
    "being",
    "between",
    "both",
    "cada",
    "case",
    "characterized",
    "com",
    "como",
    "comprising",
    "contendo",
    "compreende",
    "comprises",
    "comprising",
    "contra",
    "corresponding",
    "cujo",
    "cujos",
    "cuja",
    "cujas",
    "desde",
    "diante",
    "during",
    "each",
    "esse",
    "essa",
    "este",
    "esta",
    "estes",
    "estas",
    "from",
    "having",
    "includes",
    "including",
    "into",
    "invention",
    "method",
    "methods",
    "modo",
    "more",
    "most",
    "para",
    "pela",
    "pelo",
    "pelos",
    "pelas",
    "por",
    "process",
    "processo",
    "processos",
    "producing",
    "production",
    "provides",
    "qual",
    "quando",
    "reivindicacao",
    "relates",
    "respectively",
    "said",
    "sendo",
    "sobre",
    "such",
    "system",
    "systems",
    "step",
    "steps",
    "that",
    "their",
    "there",
    "thereby",
    "thereof",
    "these",
    "this",
    "those",
    "through",
    "uma",
    "using",
    "where",
    "wherein",
    "which",
    "with",
}


def init_db(conn: sqlite3.Connection | None = None) -> None:
    owns_connection = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA)
        ensure_admin_user(conn)
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def ensure_admin_user(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (settings.admin_user,)
    ).fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
        (settings.admin_user, hash_password(settings.admin_password), utcnow()),
    )


def authenticate(username: str, password: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return row
    return None


def scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def first_line(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.replace(";", "\n").splitlines():
        part = part.strip()
        if part:
            return part
    return value.strip()


def insert_document(
    conn: sqlite3.Connection,
    values: dict[str, Any],
    raw: dict[str, Any] | None = None,
    extracted: dict[str, Any] | None = None,
) -> int:
    now = utcnow()
    canonical = {key: clean_text(values.get(key)) for key in DOCUMENT_FIELDS.values()}
    primary_identifier = clean_text(values.get("primary_identifier")) or first_line(
        canonical.get("publication_numbers")
    )
    doc_type = clean_text(values.get("document_type")) or "patente"
    payload = {
        "import_run_id": values.get("import_run_id"),
        "document_type": doc_type,
        "primary_identifier": primary_identifier,
        **canonical,
        "source_filename": clean_text(values.get("source_filename")),
        "stored_filename": clean_text(values.get("stored_filename")),
        "stored_path": clean_text(values.get("stored_path")),
        "file_sha256": clean_text(values.get("file_sha256")),
        "extraction_status": clean_text(values.get("extraction_status")) or "imported",
        "extraction_message": clean_text(values.get("extraction_message")),
        "extracted_json": json.dumps(extracted or values.get("extracted_json"), ensure_ascii=False)
        if (extracted or values.get("extracted_json"))
        else None,
        "raw_json": json.dumps(raw or values.get("raw_json"), ensure_ascii=False)
        if (raw or values.get("raw_json"))
        else None,
        "created_at": now,
        "updated_at": now,
    }
    columns = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    cur = conn.execute(
        f"INSERT INTO documents ({columns}) VALUES ({placeholders})", tuple(payload.values())
    )
    return int(cur.lastrowid)


def list_documents(
    conn: sqlite3.Connection,
    q: str = "",
    office: str = "",
    year: str = "",
    status: str = "",
    category: str = "",
    limit: int = 80,
    offset: int = 0,
) -> list[dict[str, Any]]:
    joins: list[str] = []
    clauses: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        clauses.append(
            """
            (
                d.title LIKE ? OR d.abstract LIKE ? OR d.claims LIKE ? OR
                d.invention_description LIKE ? OR d.publication_numbers LIKE ? OR
                d.inventors LIKE ? OR d.assignees LIKE ? OR d.cpc LIKE ? OR d.ipc LIKE ?
            )
            """
        )
        params.extend([like] * 9)
    if office:
        clauses.append("d.office = ?")
        params.append(office)
    if year:
        clauses.append("d.application_year = ?")
        params.append(year)
    if status:
        clauses.append("d.family_legal_status = ?")
        params.append(status)
    if category:
        joins.append("JOIN document_categories cat ON cat.document_id = d.id")
        clauses.append("(cat.group_name = ? OR cat.subgroup_name = ? OR cat.field_label = ?)")
        params.extend([category, category, category])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT DISTINCT d.id, d.primary_identifier, d.document_type, d.title, d.abstract,
               d.publication_numbers, d.priority_date, d.application_year, d.office,
               d.family_legal_status, d.family_legal_state, d.assignees, d.inventors
        FROM documents d
        {' '.join(joins)}
        {where}
        ORDER BY COALESCE(d.application_year, '') DESC, d.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return [dict(row) for row in conn.execute(sql, params)]


def get_document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        return None
    document = dict(row)
    cats = conn.execute(
        """
        SELECT group_name, subgroup_name, field_label, value_text, flag_value
        FROM document_categories
        WHERE document_id = ?
        ORDER BY group_name, subgroup_name, field_label
        """,
        (document_id,),
    ).fetchall()
    fields = conn.execute(
        """
        SELECT sc.column_index, sc.letter, sc.header, sc.group_name, sc.subgroup_name,
               dfv.value
        FROM document_field_values dfv
        JOIN source_columns sc ON sc.id = dfv.source_column_id
        WHERE dfv.document_id = ?
        ORDER BY sc.column_index
        """,
        (document_id,),
    ).fetchall()
    document["categories"] = [dict(row) for row in cats]
    document["fields"] = [dict(row) for row in fields]
    return document


def facet_rows(conn: sqlite3.Connection, column: str, limit: int = 100) -> list[dict[str, Any]]:
    allowed = {"office", "application_year", "family_legal_status", "family_legal_state"}
    if column not in allowed:
        raise ValueError("invalid facet")
    rows = conn.execute(
        f"""
        SELECT {column} AS value, COUNT(*) AS count
        FROM documents
        WHERE {column} IS NOT NULL AND TRIM({column}) <> ''
        GROUP BY {column}
        ORDER BY count DESC, value ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    total = scalar(conn, "SELECT COUNT(*) FROM documents") or 0
    pending = scalar(
        conn,
        "SELECT COUNT(*) FROM documents WHERE family_legal_status LIKE '%PENDING%'",
    ) or 0
    alive = scalar(
        conn,
        "SELECT COUNT(*) FROM documents WHERE family_legal_state LIKE '%ALIVE%'",
    ) or 0
    first_year = scalar(
        conn,
        "SELECT MIN(CAST(application_year AS INTEGER)) FROM documents WHERE application_year GLOB '[0-9][0-9][0-9][0-9]'",
    )
    last_year = scalar(
        conn,
        "SELECT MAX(CAST(application_year AS INTEGER)) FROM documents WHERE application_year GLOB '[0-9][0-9][0-9][0-9]'",
    )
    categories = conn.execute(
        """
        SELECT COALESCE(NULLIF(group_name, ''), 'Sem grupo') AS value, COUNT(DISTINCT document_id) AS count
        FROM document_categories
        GROUP BY value
        ORDER BY count DESC, value ASC
        """
    ).fetchall()
    assignees = conn.execute(
        """
        SELECT assignees AS value, COUNT(*) AS count
        FROM documents
        WHERE assignees IS NOT NULL AND TRIM(assignees) <> ''
        GROUP BY assignees
        ORDER BY count DESC
        LIMIT 12
        """
    ).fetchall()
    return {
        "total": total,
        "pending": pending,
        "alive": alive,
        "first_year": first_year,
        "last_year": last_year,
        "offices": facet_rows(conn, "office", 60),
        "years": facet_rows(conn, "application_year", 80),
        "statuses": facet_rows(conn, "family_legal_status", 20),
        "states": facet_rows(conn, "family_legal_state", 20),
        "categories": [dict(row) for row in categories],
        "assignees": [dict(row) for row in assignees],
    }


def project_map_point(lat: float, lon: float) -> dict[str, float]:
    return {
        "x": round(((lon + 180.0) / 360.0) * 100.0, 2),
        "y": round(((90.0 - lat) / 180.0) * 100.0, 2),
    }


def world_map(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT office, COUNT(*) AS count
        FROM documents
        GROUP BY office
        ORDER BY count DESC, office ASC
        """
    ).fetchall()
    points: list[dict[str, Any]] = []
    unlocated = 0
    for row in rows:
        office = clean_text(row["office"])
        count = int(row["count"])
        if not office or office not in OFFICE_LOCATIONS:
            unlocated += count
            continue
        location = OFFICE_LOCATIONS[office]
        point = {
            "office": office,
            "count": count,
            **location,
            **project_map_point(location["lat"], location["lon"]),
        }
        points.append(point)
    max_count = max((point["count"] for point in points), default=1)
    for point in points:
        point["radius"] = round(8 + 16 * math.sqrt(point["count"] / max_count), 2)
    return {"points": points, "unlocated": unlocated}


def normalize_keyword(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def keyword_rows(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    counter: Counter[str] = Counter()
    variants: dict[str, Counter[str]] = defaultdict(Counter)
    rows = conn.execute(
        """
        SELECT title, abstract
        FROM documents
        WHERE (title IS NOT NULL AND TRIM(title) <> '')
           OR (abstract IS NOT NULL AND TRIM(abstract) <> '')
        """
    )
    for row in rows:
        text = f"{row['title'] or ''} {row['abstract'] or ''}"
        for token in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ-]{3,}", text):
            display = token.strip("-").lower()
            normalized = normalize_keyword(display)
            if (
                len(normalized) < 4
                or normalized in STOPWORDS
                or re.search(r"\d", normalized)
                or re.match(r"^[a-z]{1,3}$", normalized)
                or re.match(r"^[a-z]{2}\d", normalized)
            ):
                continue
            counter[normalized] += 1
            variants[normalized][display] += 1
    items = []
    for normalized, count in counter.most_common(limit):
        display = variants[normalized].most_common(1)[0][0]
        items.append({"term": display, "count": count})
    return items


def healthcheck(conn: sqlite3.Connection) -> dict[str, Any]:
    document_count = scalar(conn, "SELECT COUNT(*) FROM documents") or 0
    return {
        "ok": True,
        "database": "ok",
        "documents": document_count,
        "gemini_configured": bool(settings.gemini_api_key),
    }


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
