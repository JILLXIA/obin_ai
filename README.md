# Filing — Apple 2023 Form 10-K chatbot

A local React + FastAPI application that answers independent questions from the included `_10-K-Q4-2023-As-Filed.pdf`. Answers use OpenAI `gpt-6-luna` and include verified evidence references, section paths, PDF page numbers, printed page labels, source excerpts, and highlights in the original PDF.

The source document is hardcoded. There are no uploads, accounts, external document sources, conversation memory, or new financial calculations. The chat transcript lasts only until the page is refreshed.

## Start locally

Requires Python 3.12 or newer and Node.js 22.12 or newer. This workspace was tested with Python 3.14 and Node.js 24.

```bash
# Use the existing venv, or create one on a fresh checkout:
python3 -m venv venv
source venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
npm --prefix frontend ci
```

Copy `.env.example` to `.env` if `.env` does not exist. Set your key locally:

```dotenv
OPENAI_API_KEY=your_api_key_here
ANSWER_MODEL=gpt-6-luna
EMBEDDING_MODEL=text-embedding-3-small
```

The account must have access to both models. Keys stay on the backend; do not put them in a `VITE_` variable or commit `.env`.

```bash
# Extract the PDF, verify section anchors, and prepare cached embeddings.
python -m app.ingest

# Compile the interface and start the packaged local app.
npm --prefix frontend run build
python main.py
```

Open **http://127.0.0.1:8010**. The backend binds only to localhost. Keep its terminal open; use Ctrl+C to stop it. Restart after changing `.env` or rebuilding the frontend. If the server was already running while ingestion completed, use **Check connection** in the interface to load the prepared index.

Without an API key, document browsing and offline tests work. Prepare a text-only index with:

```bash
python -m app.ingest --text-only
```

The UI explicitly shows setup is required until the key and semantic index are ready. It never substitutes a fake answer for an unavailable LLM.

### Frontend development

Run these in two terminals with the Python environment activated:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
npm --prefix frontend run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to port 8010.

## How answers and citations work

1. **Extract:** `pdfplumber` reads each page in visual reading order. The reviewed section map uses the document bookmarks and visible headings, including subtitles and exhibits. The map is checksum-bound to this exact PDF, and its text anchors are validated on ingestion.
2. **Chunk:** prose is split at paragraph boundaries into approximately 600-token passages, with up to 80 estimated tokens of whole-paragraph overlap. Boundaries never cross a section or page. A table-bearing section on a page stays intact with its years, units, rows, and footnotes. Headings and the table of contents are retained for document coverage but are not retrieved as standalone evidence.
3. **Index:** SQLite stores the original passage text, source coordinates, section paths, and embeddings. FTS5 supplies keyword search. Cached vectors use `text-embedding-3-small` and cosine similarity through NumPy. A separate vector database is unnecessary for this corpus.
4. **Retrieve:** take the top 20 matches from each search method, combine with reciprocal rank fusion, and assemble up to 12 passages, including relevant adjacent continuations. Use a conservative 12,000-token estimate to bound evidence size.
5. **Generate:** `gpt-6-luna` returns structured statements and evidence IDs. It receives no conversation history, browsing tools, or additional documents.
6. **Verify:** deterministic checks reject unknown IDs and uncited statements. A separate `gpt-6-luna` call checks each statement against its own citations, including reporting years and financial units. One correction attempt is allowed; an unverified result becomes an insufficient-evidence response.
7. **Resolve:** the server supplies all citation metadata and verbatim extracted excerpts from its local records. The model cannot invent page numbers or section names. PDF.js draws source rectangles using normalized coordinates measured from the top-left of the page.

PDF page 31 is printed page 28. Printed page labels are stored separately because front matter and exhibits use different numbering. Line numbers are intentionally omitted in this version.

The original PDF stays on disk. Its extracted passages are sent to OpenAI for embeddings, and retrieved passages are sent for answering and verification. Response calls use `store=False`; provider data policies still apply.

### Cache behavior

The index records the PDF checksum, section-map checksum, extraction version, and embedding model. Unchanged data reuses cached embeddings. Each completed embedding batch is saved, so interrupted ingestion can resume.

```bash
# Recompute extraction and embeddings explicitly:
python -m app.ingest --rebuild
```

The server detects changed/stale indexes and refuses to answer with mismatched evidence. The PDF is deliberately fixed for v1. If replacing it during future development, regenerate `app/resources/sections.json` with `python scripts/build_section_map.py`, review the headings against the document, update page-count assumptions and evaluations, and rebuild the index. This helper is specific to the current filing, not a general-purpose document importer.

## API

Interactive API documentation: **http://127.0.0.1:8010/docs**.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/chat` | Accepts only `{ "query": "..." }`, up to 2,000 characters |
| GET | `/api/document` | Document identity, title, filename, page count, PDF URL |
| GET | `/api/document/pdf` | Original PDF, with byte-range support |
| GET | `/api/health` | Index readiness, key configuration, and model name |

The chat response has `status`, `answer_blocks`, `citations`, and `request_id`. Each block contains plain text and its `citation_ids`. Each citation contains its ID, document ID, section path, PDF page, optional printed page, original excerpt, and highlight rectangles.

Statuses are `answered`, `partial`, `insufficient_evidence`, and `needs_clarification`. A missing answer is not proof that information is absent from the entire filing. Requests that rely on earlier conversation must supply their own context.

Errors use `{ "error": { "code": "...", "message": "..." }, "request_id": "..." }`. Invalid queries return 422; rate limits or a busy server return 429; provider/configuration failures return 503; timeouts return 504. Technical failures are distinct from insufficient evidence. Request IDs, timing, and model token usage are logged without question text, answers, or keys. API requests are not browser-cached. Two concurrent questions are allowed.

## Tests and evaluation

```bash
python -m pytest -q
python -m ruff check app scripts tests main.py
npm --prefix frontend test
npm --prefix frontend run build

# No OpenAI calls: evaluate keyword retrieval against known passages.
python -m app.evaluate

# Paid API calls: evaluate hybrid retrieval and generate answers for review.
python -m app.evaluate --live
```

`evaluations/questions.json` contains 26 cases: 21 answerable questions with supporting pages and evidence strings, plus out-of-document questions, unsupported arithmetic, an independent follow-up, and an instruction-boundary case. Reports are written under `data/`. The offline score is keyword evidence recall, not semantic-search quality or answer accuracy. The test gate requires at least 90% of answerable cases to retrieve their supporting evidence.

For a live run, inspect every generated answer and set its report's `human_review` field after comparing all factual statements, years, units, and citations with the actual PDF. The model-based grounding check can still make mistakes; citation validity alone does not establish that an answer is correct. Broad summaries cover retrieved evidence and do not promise exhaustive coverage.

### Browser checks

Start the built application, then run:

```bash
python scripts/browser_fixture.py
cd frontend
npx playwright install chromium
npm run test:e2e
```

To use an installed Chrome instead of downloading Chromium on macOS:

```bash
BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm --prefix frontend run test:e2e
```

The browser check uses the real PDF and backend, but mocks the chat response with actual citation metadata. It checks PDF rendering, page navigation, retry behavior, source excerpts, source highlights, mobile layout, and clearing the transcript. Screenshots are saved under `data/browser-checks/`. It does not call OpenAI or establish generated-answer accuracy.

## Project layout

```text
app/                  FastAPI, extraction, search, OpenAI integration, verification
app/resources/        Checksum-bound section map
frontend/             React UI, PDF.js viewer, interface and browser tests
evaluations/          Reviewed questions and supporting evidence
scripts/              Section-map maintenance and browser fixture generation
tests/                Document, retrieval, API, provider, and grounding tests
data/                 Ignored local indexes, embeddings, and test reports
```
