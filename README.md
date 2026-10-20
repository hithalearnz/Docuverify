# DocuVerify AI — Document Integrity, Validation and Evidence Search

A starter project for demonstrating Python backend engineering, PDF text extraction, SHA-256 integrity checks, metadata validation, document search, and evidence-grounded Q&A.

## Current MVP scope
- Upload PDF documents through a FastAPI REST API.
- Extract text from text-based PDFs using `pypdf`.
- Compute and store a SHA-256 file hash.
- Flag missing metadata fields supplied by the user.
- Verify a later file against the originally uploaded file hash.
- Search stored documents and return matching text chunks with document IDs and page numbers.
- Answer questions by returning relevant evidence passages. This MVP is **extractive evidence retrieval**, not an LLM-generated RAG system yet.
- SQLite persistence for a zero-configuration local run.
- Swagger API docs at `/docs`.

## Important limitations
- A matching SHA-256 hash establishes byte-for-byte file integrity only. It does not prove that a document or its claims are authentic.
- Scanned PDFs require OCR; this version reports that no text could be extracted rather than pretending OCR succeeded.
- Search is lexical and lightweight. Add embeddings/vector search and a grounded LLM answer step before describing the project as a complete generative RAG implementation.
- This is a development prototype, not a production security or compliance system.

## Setup (Windows PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```
If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again. Alternatively, use `.venv\Scripts\python.exe` directly.

Open `http://127.0.0.1:8000/docs`.

## Quick workflow
1. POST `/documents` with a PDF file and form fields `title`, `issuer`, `reference_number`, `document_date`.
2. POST `/documents/{document_id}/verify` with the same or modified PDF as `file`.
3. POST `/search` with JSON: `{"query":"the topic to find","limit":5}`.
4. POST `/ask` with JSON: `{"question":"What does the uploaded document say about ...?","limit":3}`.

## Tests
```powershell
pytest -q
```

## Next milestones
1. Add OCR for scanned PDFs (for example, Tesseract with explicit installation instructions).
2. Add embeddings and a vector store, with retrieval evaluation (Recall@k / MRR).
3. Add an optional LLM answer layer that must cite retrieved passages and abstain when evidence is insufficient.
4. Add authentication, file-size limits, malware scanning, rate limits, audit logs, and deployment hardening.
5. Add a frontend and a documented evaluation dataset.
