import asyncio
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import DOCUMENT_TITLE, PDF_PATH, ROOT, Settings
from app.index import Index, expected_metadata, read_metadata
from app.models import ChatRequest, ChatResponse
from app.provider import InvalidModelResponse, OpenAIProvider
from app.service import ChatService

logger = logging.getLogger("filing_chat")


def create_app(settings: Settings | None = None, service=None) -> FastAPI:
    settings = settings or Settings()
    state = {
        "index": None,
        "service": service,
        "index_status": "missing",
        "provider": None,
        "fingerprint": None,
    }
    semaphore = asyncio.Semaphore(2)

    @asynccontextmanager
    async def lifespan(application):
        refresh_index()
        yield
        if state["provider"]:
            await state["provider"].close()

    app = FastAPI(title="Filing / Apple 2023 10-K", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    def refresh_index():
        try:
            from app.config import SECTION_MAP_PATH

            fingerprint = tuple(
                (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                for p in (settings.index_path, PDF_PATH, SECTION_MAP_PATH)
            )
            if fingerprint == state["fingerprint"]:
                return
            state["fingerprint"] = fingerprint
            state["index"] = None
            if not service:
                state["service"] = None
            metadata = read_metadata(settings.index_path)
            if not metadata:
                state["index_status"] = "missing"
                return
            if metadata != expected_metadata(settings.embedding_model):
                state["index_status"] = "stale"
                return
            index = Index(settings.index_path)
            state["index"] = index
            state["index_status"] = "ready" if index.semantic_ready else "text_only"
            if index.semantic_ready and settings.api_key and not service:
                if state["provider"] is None:
                    state["provider"] = OpenAIProvider(settings)
                state["service"] = ChatService(index, state["provider"])
        except (OSError, ValueError, sqlite3.DatabaseError):
            state["index_status"] = "invalid"

    def error(code, message, status, request_id):
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message}, "request_id": request_id},
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/") and request.url.path != "/api/document/pdf":
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request id=%s method=%s path=%s status=%s duration_ms=%.0f",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def bad_input(request, exc):
        return error(
            "invalid_query",
            "Enter a non-empty question of at most 2,000 characters. Only the query field is accepted.",
            422,
            request.state.request_id,
        )

    @app.get("/api/health")
    def health():
        # A finished CLI ingest becomes visible without restarting the server.
        refresh_index()
        return {
            "status": "ready" if settings.api_key and state["index_status"] == "ready" else "setup_required",
            "index_status": state["index_status"],
            "api_key_configured": bool(settings.api_key),
            "model": settings.answer_model,
            "passage_count": len(state["index"].passages) if state["index"] else 0,
        }

    @app.get("/api/document")
    def document():
        metadata = read_metadata(settings.index_path)
        return {
            "id": metadata.get("pdf_sha256", "")[:16],
            "title": DOCUMENT_TITLE,
            "filename": PDF_PATH.name,
            "page_count": 80,
            "pdf_url": "/api/document/pdf",
        }

    @app.get("/api/document/pdf")
    def pdf():
        return FileResponse(
            PDF_PATH, media_type="application/pdf", filename=PDF_PATH.name, content_disposition_type="inline"
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        request_id = request.state.request_id
        if not service:
            refresh_index()
            if not settings.api_key:
                return error(
                    "api_key_missing",
                    "Add OPENAI_API_KEY to the local .env file, prepare the index, and restart the backend.",
                    503,
                    request_id,
                )
            if state["index_status"] != "ready":
                return error(
                    "index_not_ready",
                    "The document index is not ready. Run python -m app.ingest, then check readiness.",
                    503,
                    request_id,
                )
        acquired = False
        try:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=1)
            except TimeoutError:
                return error(
                    "server_busy",
                    "Two questions are already being processed. Please retry shortly.",
                    429,
                    request_id,
                )
            acquired = True
            async with asyncio.timeout(170):
                return await state["service"].answer(body.query, request_id)
        except (APITimeoutError, TimeoutError):
            return error("request_timeout", "The request took too long. Please try again.", 504, request_id)
        except AuthenticationError:
            return error(
                "provider_auth",
                "OpenAI rejected the API key. Check the backend .env configuration.",
                503,
                request_id,
            )
        except RateLimitError:
            return error(
                "provider_rate_limit",
                "OpenAI is rate-limiting requests or the account quota is exhausted. Check usage and retry.",
                429,
                request_id,
            )
        except APIConnectionError:
            return error(
                "provider_connection",
                "Could not connect to OpenAI. Check your connection and retry.",
                503,
                request_id,
            )
        except InvalidModelResponse:
            return error("invalid_model_response", "The model did not return a complete answer after retrying. Please try again.", 502, request_id)
        except APIStatusError:
            return error(
                "provider_unavailable",
                "OpenAI could not complete the request. Check model access and account status, then retry.",
                503,
                request_id,
            )
        except Exception as exc:  # noqa: BLE001 -- Public error boundary redacts provider internals.
            logger.error("request_failed id=%s type=%s", request_id, type(exc).__name__)
            return error(
                "request_failed",
                "The answer could not be completed. Please retry; use the request ID if the issue persists.",
                500,
                request_id,
            )
        finally:
            if acquired:
                semaphore.release()

    frontend = ROOT / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:

        @app.get("/")
        def frontend_missing():
            return JSONResponse(
                {
                    "message": "Backend is running. Build the frontend with npm --prefix frontend run build, then restart; or run the Vite development server."
                }
            )

    return app


app = create_app()
