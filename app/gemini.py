from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import settings
from .extractors import extract_text, guess_mime


EXTRACTION_SCHEMA = {
    "document_type": "artigo|patente|relatorio|tese|outro",
    "primary_identifier": "DOI, numero de publicacao, numero de patente ou identificador",
    "title": "titulo principal",
    "abstract": "resumo curto em portugues",
    "publication_numbers": "numeros de publicacao ou DOI",
    "publication_dates": "datas de publicacao",
    "priority_date": "data de prioridade ou submissao",
    "inventors": "inventores ou autores",
    "assignees": "titulares, instituicoes ou empresas",
    "cpc": "classificacoes CPC",
    "ipc": "classificacoes IPC",
    "family_legal_status": "status juridico consolidado",
    "legal_status": "status por publicacao",
    "family_legal_state": "estado vivo/morto consolidado",
    "legal_state": "estado por publicacao",
    "application_year": "ano principal",
    "office": "escritorio, pais ou base",
    "keywords": ["palavras-chave"],
    "technological_routes": ["rotas tecnologicas"],
    "feedstocks": ["materias-primas"],
    "processes": ["processos"],
    "products": ["produtos"],
    "didactic_summary": "explicacao didatica do resultado e relevancia",
    "evidence": ["trechos que sustentam a extracao"],
}


def strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S | re.I)
    if match:
        return match.group(1)
    return text.strip()


def parse_json_response(text: str) -> dict[str, Any]:
    candidate = strip_json_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def build_prompt(text: str) -> str:
    return f"""
Voce e um especialista em prospeccao cientifica e tecnologica de agave,
etanol, biomassa, biorrefinarias e propriedade intelectual.

Extraia metadados e resultados do documento para alimentar um observatorio.
Responda somente com JSON valido, usando chaves em ingles conforme este modelo:

{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False, indent=2)}

Regras:
- Quando um campo nao existir, use null ou lista vazia.
- Escreva title no idioma original, mas abstract e didactic_summary em portugues.
- Diferencie artigo cientifico, patente e outros documentos.
- Em didactic_summary, explique o que o documento contribui de modo didatico.
- Em evidence, inclua frases curtas do documento que justifiquem os campos.

Texto extraido localmente, se disponivel:
{text[:60000]}
""".strip()


def gemini_extract(path: Path) -> tuple[dict[str, Any], str]:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY nao configurada.")

    text = extract_text(path)
    prompt = build_prompt(text)
    parts: list[dict[str, Any]] = [{"text": prompt}]

    file_bytes = path.read_bytes()
    if len(file_bytes) <= 18_000_000:
        parts.append(
            {
                "inline_data": {
                    "mime_type": guess_mime(path),
                    "data": base64.b64encode(file_bytes).decode("ascii"),
                }
            }
        )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Erro Gemini HTTP {exc.code}: {detail}") from exc

    candidates = response_json.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini nao retornou candidatos.")
    content = candidates[0].get("content") or {}
    response_parts = content.get("parts") or []
    response_text = "\n".join(part.get("text", "") for part in response_parts)
    if not response_text:
        raise RuntimeError("Gemini retornou resposta vazia.")
    return parse_json_response(response_text), response_text
