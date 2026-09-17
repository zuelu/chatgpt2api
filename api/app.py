from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from api import accounts, ai, image_tasks, system
from api.errors import install_exception_handlers
from api.support import resolve_web_asset
from services.config import config


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Account refresh, token keepalive, remote backup and cleanup jobs are not
        # started automatically in the restored service. Explicit authenticated
        # actions remain available through their existing API routes.
        yield

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(system.create_router(app_version))

    @app.options("/{full_path:path}", include_in_schema=False)
    async def options_fallback(full_path: str):
        return Response(status_code=204)

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            headers = {"Cache-Control": "no-store"} if asset.suffix.lower() in {".html", ".txt"} else {}
            return FileResponse(asset, headers=headers)
        clean_path = full_path.strip("/")
        if clean_path == "_next" or clean_path.startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback, headers={"Cache-Control": "no-store"})

    return app
