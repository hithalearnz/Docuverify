from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DOCUVERIFY_DATA_DIR", str(APP_DIR.parent / "data")))
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "docuverify.sqlite3"
MAX_FILE_BYTES = 15 * 1024 * 1024

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="DocuVerify AI API",
    description="Document integrity checks, metadata validation, and evidence search.",
    version="0.1.0",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                issuer TEXT,
                reference_number TEXT,
                document_date TEXT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                extracted_text TEXT NOT NULL,
                pages_json TEXT NOT NULL,
                missing_fields_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


init_db()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf(data: bytes) -> list[dict]:
    import io
    try:
        reader = PdfReader(io.BytesIO(data))
        result = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                result.append({"page": index, "text": text})
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc


def chunk_text(pages: list[dict], chunk_size: int = 900) -> list[dict]:
    chunks = []
    for page in pages:
        text = re.sub(r"\s+", " ", page["text"]).strip()
        for start in range(0, len(text), chunk_size):
            piece = text[start:start + chunk_size].strip()
            if piece:
                chunks.append({"page": page["page"], "text": piece})
    return chunks


def missing_metadata(title: str, issuer: Optional[str],
                     reference_number: Optional[str], document_date: Optional[str]) -> list[str]:
    required = {
        "title": title,
        "issuer": issuer,
        "reference_number": reference_number,
        "document_date": document_date,
    }
    return [key for key, value in required.items() if not value or not value.strip()]


@app.get("/health")
def health():
    return {"status": "ok", "service": "DocuVerify AI", "time": now_iso()}


@app.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=200),
    issuer: Optional[str] = Form(None),
    reference_number: Optional[str] = Form(None),
    document_date: Optional[str] = Form(None),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Upload a PDF file.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Maximum PDF size is 15 MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not have a PDF header.")

    pages = extract_pdf(data)
    if not pages:
        raise HTTPException(
            status_code=422,
            detail="No selectable text found. The PDF may be scanned; OCR is not included in this MVP."
        )

    doc_id = str(uuid.uuid4())
    digest = sha256_bytes(data)
    stored_filename = f"{doc_id}.pdf"
    (FILES_DIR / stored_filename).write_bytes(data)
    extracted_text = "\n".join(p["text"] for p in pages)
    missing = missing_metadata(title, issuer, reference_number, document_date)

    with connect_db() as conn:
        conn.execute("""
            INSERT INTO documents (
                id, title, issuer, reference_number, document_date,
                original_filename, stored_filename, sha256, extracted_text,
                pages_json, missing_fields_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_id, title.strip(), issuer, reference_number, document_date,
            file.filename, stored_filename, digest, extracted_text,
            json.dumps(pages), json.dumps(missing), now_iso()
        ))

    return {
        "document_id": doc_id,
        "title": title,
        "sha256": digest,
        "page_count_with_text": len(pages),
        "extracted_characters": len(extracted_text),
        "missing_metadata_fields": missing,
        "integrity_note": "SHA-256 records file integrity; it does not establish real-world authenticity."
    }


@app.get("/documents")
def list_documents():
    with connect_db() as conn:
        rows = conn.execute("""
            SELECT id, title, issuer, reference_number, document_date,
                   original_filename, sha256, missing_fields_json, created_at
            FROM documents ORDER BY created_at DESC
        """).fetchall()
    return [
        {
            "document_id": row["id"],
            "title": row["title"],
            "issuer": row["issuer"],
            "reference_number": row["reference_number"],
            "document_date": row["document_date"],
            "filename": row["original_filename"],
            "sha256": row["sha256"],
            "missing_metadata_fields": json.loads(row["missing_fields_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/documents/{document_id}")
def get_document(document_id: str):
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {
        "document_id": row["id"],
        "title": row["title"],
        "issuer": row["issuer"],
        "reference_number": row["reference_number"],
        "document_date": row["document_date"],
        "filename": row["original_filename"],
        "sha256": row["sha256"],
        "missing_metadata_fields": json.loads(row["missing_fields_json"]),
        "created_at": row["created_at"],
        "extracted_text": row["extracted_text"],
    }


@app.post("/documents/{document_id}/verify")
async def verify_document(document_id: str, file: UploadFile = File(...)):
    with connect_db() as conn:
        row = conn.execute("SELECT sha256 FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found.")
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Maximum PDF size is 15 MB.")
    received_hash = sha256_bytes(data)
    matches = received_hash == row["sha256"]
    return {
        "document_id": document_id,
        "integrity_match": matches,
        "stored_sha256": row["sha256"],
        "received_sha256": received_hash,
        "result": "BYTE_FOR_BYTE_MATCH" if matches else "FILE_CONTENTS_DIFFER",
        "note": "This check compares file bytes only; it does not prove issuer identity or truthfulness."
    }


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=3, ge=1, le=10)


def retrieve(query: str, limit: int) -> list[dict]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]+", query)]
    if not terms:
        return []
    with connect_db() as conn:
        rows = conn.execute("SELECT id, title, pages_json FROM documents").fetchall()

    hits = []
    for row in rows:
        pages = json.loads(row["pages_json"])
        for chunk in chunk_text(pages):
            text_lower = chunk["text"].lower()
            score = sum(text_lower.count(term) for term in terms)
            if score:
                hits.append({
                    "document_id": row["id"],
                    "title": row["title"],
                    "page": chunk["page"],
                    "text": chunk["text"],
                    "score": score,
                })
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:limit]


@app.post("/search")
def search_documents(request: SearchRequest):
    return {
        "query": request.query,
        "retrieval_method": "lexical term frequency (prototype; not semantic vector search)",
        "results": retrieve(request.query, request.limit),
    }


@app.post("/ask")
def ask_documents(request: AskRequest):
    evidence = retrieve(request.question, request.limit)
    if not evidence:
        return {
            "question": request.question,
            "answer": "Insufficient evidence in uploaded documents.",
            "evidence": [],
            "mode": "extractive retrieval only; no LLM generation configured",
        }
    answer = "Relevant evidence found in the uploaded documents. Review the cited passages below; this prototype does not infer facts beyond the retrieved text."
    return {
        "question": request.question,
        "answer": answer,
        "evidence": [
            {
                "document_id": item["document_id"],
                "document_title": item["title"],
                "page": item["page"],
                "excerpt": item["text"],
                "retrieval_score": item["score"],
            }
            for item in evidence
        ],
        "mode": "extractive retrieval only; no LLM generation configured",
    }
