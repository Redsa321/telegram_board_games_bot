from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from telegram import Bot

from .admin_repository import AdminRepository
from .config import Config
from .db import Database, database_path, is_postgres_url
from .telegram_retry import send_message_with_retry

WEB_DIRECTORY = Path(__file__).with_name("admin_web_static")


class AdminMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    chat_ids: list[int] = Field(default_factory=list, max_length=200)
    all_active_groups: bool = False


def create_admin_app(
    config: Config,
    *,
    database: Database | None = None,
    telegram_bot: Any | None = None,
) -> FastAPI:
    if not config.admin_web_token:
        raise RuntimeError("ADMIN_WEB_TOKEN is not set")

    owns_database = database is None
    owns_bot = telegram_bot is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_database = database or Database.connect(config.database_url)
        active_database._run_migrations()
        active_bot = telegram_bot or Bot(config.bot_token)
        if owns_bot:
            await active_bot.initialize()
        app.state.database = active_database
        app.state.repository = AdminRepository(active_database)
        app.state.telegram_bot = active_bot
        try:
            yield
        finally:
            if owns_bot:
                await active_bot.shutdown()
            if owns_database:
                active_database.close()

    app = FastAPI(title="Kyzma Admin", docs_url=None, redoc_url=None, lifespan=lifespan)

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {config.admin_web_token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    admin_access = Depends(require_admin)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return no_store_file(WEB_DIRECTORY / "index.html", "text/html")

    @app.get("/assets/app.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return no_store_file(WEB_DIRECTORY / "app.js", "text/javascript")

    @app.get("/assets/styles.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return no_store_file(WEB_DIRECTORY / "styles.css", "text/css")

    @app.get("/api/overview", dependencies=[admin_access])
    async def overview(request: Request) -> dict[str, int]:
        return repository(request).overview()

    @app.get("/api/groups", dependencies=[admin_access])
    async def groups(request: Request, q: str | None = None) -> list[dict[str, Any]]:
        return repository(request).groups(q.strip() if q else None)

    @app.get("/api/groups/{chat_id}/events", dependencies=[admin_access])
    async def group_events(
        request: Request,
        chat_id: int,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        return repository(request).events(chat_id=chat_id, limit=limit)

    @app.get("/api/activity", dependencies=[admin_access])
    async def activity(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        return repository(request).events(limit=limit)

    @app.get("/api/users", dependencies=[admin_access])
    async def users(
        request: Request,
        q: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        return repository(request).users(q.strip() if q else None, limit)

    @app.get("/api/users/{user_id}", dependencies=[admin_access])
    async def user_detail(request: Request, user_id: int) -> dict[str, Any]:
        result = repository(request).user_detail(user_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return result

    @app.post("/api/messages", dependencies=[admin_access])
    async def send_admin_message(request: Request, payload: AdminMessageRequest) -> dict[str, Any]:
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Message is empty")
        active_database: Database = request.app.state.database
        chat_ids = list(dict.fromkeys(payload.chat_ids))
        if payload.all_active_groups:
            chat_ids = [group.telegram_chat_id for group in await active_database.get_active_group_chats()]
        else:
            known_group_ids = {
                group.telegram_chat_id for group in await active_database.search_group_chats()
            }
            unknown_chat_ids = [chat_id for chat_id in chat_ids if chat_id not in known_group_ids]
            if unknown_chat_ids:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Unknown group chat IDs: {', '.join(map(str, unknown_chat_ids))}",
                )
        if not chat_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Select at least one chat")
        sent: list[int] = []
        failed: list[int] = []
        for chat_id in chat_ids:
            delivered = await send_message_with_retry(
                request.app.state.telegram_bot,
                chat_id=chat_id,
                text=text,
            )
            if delivered:
                sent.append(chat_id)
                await active_database.record_audit_event(
                    "admin_message",
                    chat_id=chat_id,
                    details={"text": text, "source": "web", "admin_user_id": config.admin_user_id},
                )
            else:
                failed.append(chat_id)
        return {"sent": sent, "failed": failed}

    return app


def repository(request: Request) -> AdminRepository:
    return request.app.state.repository


def no_store_file(path: Path, media_type: str) -> FileResponse:
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


def main() -> None:
    load_dotenv()
    config = Config.from_env()
    configured_database_path = None if is_postgres_url(config.database_url) else database_path(config.database_url)
    if config.require_existing_database and configured_database_path is not None and not configured_database_path.is_file():
        raise RuntimeError(f"configured database does not exist: {configured_database_path}")
    uvicorn.run(
        create_admin_app(config),
        host=config.admin_web_host,
        port=config.admin_web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
