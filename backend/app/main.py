import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import (
    auth,
    chat,
    connections,
    invites,
    projects,
    repos,
    rules,
    ssh_keys,
    visualizations,
    workflows,
)
from app.config import settings
from app.core.logging_config import configure_logging
from app.core.rate_limit import limiter
from app.models.base import init_db, run_migrations

configure_logging(
    json_format=os.getenv("LOG_FORMAT", "text") == "json",
    level=os.getenv("LOG_LEVEL", "INFO"),
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    await init_db()
    yield
    logger.info("Shutting down: disconnecting connectors and tunnels")
    try:
        await chat._orchestrator.disconnect_all()
    except Exception:
        logger.exception("Error during orchestrator cleanup")
    for mgr_module in (
        repos,
        __import__("app.connectors.postgres", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.mysql", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.mongodb", fromlist=["_tunnel_mgr"]),
        __import__("app.connectors.clickhouse", fromlist=["_tunnel_mgr"]),
    ):
        mgr = getattr(mgr_module, "_tunnel_mgr", None)
        if mgr and hasattr(mgr, "close_all"):
            try:
                await mgr.close_all()
            except Exception:
                logger.exception("Error closing tunnel manager")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(ssh_keys.router, prefix="/api/ssh-keys", tags=["ssh-keys"])
app.include_router(visualizations.router, prefix="/api/visualizations", tags=["visualizations"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(rules.router, prefix="/api/rules", tags=["rules"])
app.include_router(invites.router, prefix="/api/invites", tags=["invites"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/health/modules")
async def module_health():
    """Per-module health checks for independent debugging."""
    results: dict[str, dict] = {}

    # Internal database
    try:
        from app.models.base import async_session_factory
        async with async_session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        results["database"] = {"status": "ok"}
    except Exception as e:
        results["database"] = {"status": "error", "detail": str(e)}

    # Vector store (ChromaDB)
    try:
        from app.knowledge.vector_store import VectorStore
        vs = VectorStore()
        vs._client.heartbeat()
        results["vector_store"] = {"status": "ok"}
    except Exception as e:
        results["vector_store"] = {"status": "error", "detail": str(e)}

    # SSH tunnels
    try:
        tunnel_info = []
        for mod_path in ("app.connectors.postgres", "app.connectors.mysql"):
            try:
                mod = __import__(mod_path, fromlist=["_tunnel_mgr"])
                mgr = getattr(mod, "_tunnel_mgr", None)
                if mgr:
                    tunnel_info.append({"module": mod_path, "active_tunnels": len(mgr._tunnels)})
            except Exception:
                pass
        results["ssh_tunnels"] = {"status": "ok", "detail": tunnel_info}
    except Exception as e:
        results["ssh_tunnels"] = {"status": "error", "detail": str(e)}

    # Active connectors
    try:
        active = list(chat._orchestrator._connectors.keys())
        results["connectors"] = {"status": "ok", "active": len(active), "keys": active}
    except Exception as e:
        results["connectors"] = {"status": "error", "detail": str(e)}

    # LLM provider
    try:
        import asyncio
        import time

        from app.llm.base import Message
        from app.llm.router import LLMRouter

        llm = LLMRouter()
        start = time.monotonic()
        await asyncio.wait_for(
            llm.complete([Message(role="user", content="ping")], max_tokens=1),
            timeout=5.0,
        )
        elapsed = round((time.monotonic() - start) * 1000, 1)
        results["llm"] = {
            "status": "ok",
            "provider": llm._chain[0] if llm._chain else "unknown",
            "response_time_ms": elapsed,
        }
        await llm.close()
    except TimeoutError:
        results["llm"] = {"status": "error", "detail": "Timeout (5s)"}
    except Exception as e:
        results["llm"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(r["status"] == "ok" for r in results.values()) else "degraded"
    return {"status": overall, "modules": results}
