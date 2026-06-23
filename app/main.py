from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from . import db
from .config import BASE_DIR, settings
from .gemini import gemini_extract


templates = Jinja2Templates(directory=str(BASE_DIR / "app/templates"))


def json_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def require_user(request: Request) -> int | None:
    user_id = request.session.get("user_id")
    return int(user_id) if user_id else None


def sanitize_filename(value: str, fallback: str = "documento") -> str:
    value = re.sub(r"[^\w\s.-]+", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "-", value).strip("-._")
    return value[:90] or fallback


def value_from_extraction(extracted: dict[str, Any], key: str) -> str | None:
    value = extracted.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "logged_in": bool(require_user(request)),
            "username": request.session.get("username"),
        },
    )


async def api_me(request: Request):
    return JSONResponse(
        {
            "logged_in": bool(require_user(request)),
            "username": request.session.get("username"),
        }
    )


async def login(request: Request):
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    user = db.authenticate(username, password)
    if not user:
        return json_error("Usuario ou senha invalidos.", 401)
    request.session["user_id"] = int(user["id"])
    request.session["username"] = user["username"]
    return JSONResponse({"ok": True, "username": user["username"]})


async def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


async def api_summary(request: Request):
    with db.get_conn() as conn:
        return JSONResponse(db.summary(conn))


async def health(request: Request):
    try:
        with db.get_conn() as conn:
            return JSONResponse(db.healthcheck(conn))
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "database": "error", "error": type(exc).__name__},
            status_code=503,
        )


async def api_facets(request: Request):
    with db.get_conn() as conn:
        return JSONResponse(
            {
                "offices": db.facet_rows(conn, "office", 120),
                "years": db.facet_rows(conn, "application_year", 200),
                "statuses": db.facet_rows(conn, "family_legal_status", 40),
                "states": db.facet_rows(conn, "family_legal_state", 40),
                "categories": [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT value, COUNT(*) AS count
                        FROM (
                            SELECT DISTINCT document_id, group_name AS value
                            FROM document_categories
                            WHERE group_name IS NOT NULL AND TRIM(group_name) <> ''
                            UNION
                            SELECT DISTINCT document_id, subgroup_name AS value
                            FROM document_categories
                            WHERE subgroup_name IS NOT NULL AND TRIM(subgroup_name) <> ''
                        )
                        GROUP BY value
                        ORDER BY count DESC, value ASC
                        """
                    )
                ],
            }
        )


async def api_world_map(request: Request):
    with db.get_conn() as conn:
        return JSONResponse(db.world_map(conn))


async def api_keywords(request: Request):
    limit = int(request.query_params.get("limit", 50))
    with db.get_conn() as conn:
        return JSONResponse({"items": db.keyword_rows(conn, limit=limit)})


async def api_documents(request: Request):
    qp = request.query_params
    with db.get_conn() as conn:
        rows = db.list_documents(
            conn,
            q=qp.get("q", "").strip(),
            office=qp.get("office", "").strip(),
            year=qp.get("year", "").strip(),
            status=qp.get("status", "").strip(),
            category=qp.get("category", "").strip(),
            limit=min(int(qp.get("limit", 80)), 200),
            offset=max(int(qp.get("offset", 0)), 0),
        )
    return JSONResponse({"items": rows})


async def api_document_detail(request: Request):
    document_id = int(request.path_params["document_id"])
    with db.get_conn() as conn:
        document = db.get_document(conn, document_id)
    if not document:
        return json_error("Documento nao encontrado.", 404)
    return JSONResponse(document)


async def api_download(request: Request):
    document_id = int(request.path_params["document_id"])
    if not require_user(request):
        return json_error("Login necessario.", 401)
    with db.get_conn() as conn:
        document = db.get_document(conn, document_id)
    if not document or not document.get("stored_path"):
        return json_error("Arquivo nao encontrado.", 404)
    path = Path(document["stored_path"])
    if not path.exists():
        return json_error("Arquivo nao existe no servidor.", 404)
    return FileResponse(path, filename=document.get("stored_filename") or path.name)


async def api_upload(request: Request):
    if not require_user(request):
        return json_error("Login necessario.", 401)
    form = await request.form()
    upload = form.get("document")
    if not isinstance(upload, UploadFile):
        return json_error("Envie um arquivo no campo document.")

    settings.resolved_upload_dir().mkdir(parents=True, exist_ok=True)
    original_name = upload.filename or "documento"
    suffix = Path(original_name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await upload.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    file_hash = hashlib.sha256(content).hexdigest()
    extraction_status = "extracted"
    extraction_message = None
    extracted: dict[str, Any] = {}
    try:
        extracted, raw_response = gemini_extract(tmp_path)
        extracted["_gemini_raw_response"] = raw_response
    except Exception as exc:
        extraction_status = "error"
        extraction_message = str(exc)

    title_or_id = (
        value_from_extraction(extracted, "primary_identifier")
        or value_from_extraction(extracted, "title")
        or Path(original_name).stem
    )
    stored_filename = f"{sanitize_filename(title_or_id)}-{file_hash[:10]}{suffix}"
    stored_path = settings.resolved_upload_dir() / stored_filename
    shutil.move(str(tmp_path), stored_path)

    values = {
        "document_type": value_from_extraction(extracted, "document_type") or "documento",
        "primary_identifier": value_from_extraction(extracted, "primary_identifier"),
        "publication_numbers": value_from_extraction(extracted, "publication_numbers"),
        "publication_dates": value_from_extraction(extracted, "publication_dates"),
        "priority_date": value_from_extraction(extracted, "priority_date"),
        "title": value_from_extraction(extracted, "title") or Path(original_name).stem,
        "abstract": value_from_extraction(extracted, "abstract")
        or value_from_extraction(extracted, "didactic_summary"),
        "claims": value_from_extraction(extracted, "claims"),
        "invention_description": value_from_extraction(extracted, "didactic_summary"),
        "inventors": value_from_extraction(extracted, "inventors"),
        "assignees": value_from_extraction(extracted, "assignees"),
        "cpc": value_from_extraction(extracted, "cpc"),
        "ipc": value_from_extraction(extracted, "ipc"),
        "family_legal_status": value_from_extraction(extracted, "family_legal_status"),
        "legal_status": value_from_extraction(extracted, "legal_status"),
        "family_legal_state": value_from_extraction(extracted, "family_legal_state"),
        "legal_state": value_from_extraction(extracted, "legal_state"),
        "application_year": value_from_extraction(extracted, "application_year"),
        "office": value_from_extraction(extracted, "office"),
        "source_filename": original_name,
        "stored_filename": stored_filename,
        "stored_path": str(stored_path),
        "file_sha256": file_hash,
        "extraction_status": extraction_status,
        "extraction_message": extraction_message,
    }

    with db.get_conn() as conn:
        document_id = db.insert_document(conn, values, extracted=extracted)
        for group in [
            ("Produto", "products"),
            ("Processo", "processes"),
            ("Rota Tecnologica", "technological_routes"),
            ("Materia-prima", "feedstocks"),
            ("Palavras-chave", "keywords"),
        ]:
            group_name, key = group
            items = extracted.get(key) or []
            if isinstance(items, str):
                items = [items]
            for item in items:
                if item:
                    conn.execute(
                        """
                        INSERT INTO document_categories(document_id, group_name, field_label,
                                                        value_text, flag_value)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (document_id, group_name, str(item), str(item)),
                    )
    return JSONResponse(
        {
            "ok": True,
            "document_id": document_id,
            "stored_filename": stored_filename,
            "extraction_status": extraction_status,
            "extraction_message": extraction_message,
        }
    )


async def api_import_spreadsheet(request: Request):
    if not require_user(request):
        return json_error("Login necessario.", 401)
    form = await request.form()
    upload = form.get("spreadsheet")
    if not isinstance(upload, UploadFile):
        return json_error("Envie uma planilha no campo spreadsheet.")
    import_dir = settings.base_dir / "data/imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    path = import_dir / sanitize_filename(upload.filename or "planilha.xlsx")
    path.write_bytes(await upload.read())
    from .importer import import_spreadsheet

    result = import_spreadsheet(path)
    return JSONResponse({"ok": True, "result": result})


routes = [
    Route("/", index),
    Route("/health", health),
    Route("/api/me", api_me),
    Route("/api/login", login, methods=["POST"]),
    Route("/api/logout", logout, methods=["POST"]),
    Route("/api/summary", api_summary),
    Route("/api/facets", api_facets),
    Route("/api/world-map", api_world_map),
    Route("/api/keywords", api_keywords),
    Route("/api/documents", api_documents),
    Route("/api/documents/{document_id:int}", api_document_detail),
    Route("/api/documents/{document_id:int}/download", api_download),
    Route("/api/upload", api_upload, methods=["POST"]),
    Route("/api/import-spreadsheet", api_import_spreadsheet, methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(BASE_DIR / "app/static")), name="static"),
]


app = Starlette(debug=settings.debug, routes=routes)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
db.init_db()
