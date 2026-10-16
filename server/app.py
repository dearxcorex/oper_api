"""HTTP wrapper around NbtcOper for fm-station-tracker's Discord /ask bot.

Runs on a home machine because Cloudflare challenges the portal from cloud IPs
(Vercel included), and is reached through Tailscale Funnel. Read-only, and
never returns coordinates: only find_stations summaries and inspection counts.
find_stations answers from the saved register (python -m nbtc_oper register)
when there is one, and walks the portal live, within LIVE_TIME_LIMIT, when
there is not. POST /refresh rebuilds the register in the background.

    uv run --group server uvicorn server.app:app --host 127.0.0.1 --port 8787

Every route but /health needs `Authorization: Bearer $OPER_API_TOKEN`.
"""
import logging
import os
import secrets
import threading
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nbtc_oper import config, register
from nbtc_oper import CloudflareChallenge, CredentialsNotFound, LoginFailed, NbtcError, NbtcOper
from nbtc_oper.places import UnknownPlace

DETAILS_LIMIT = 10  # live, details costs one portal request per station shown
LIVE_TIME_LIMIT = 20  # seconds; the bot's tool budget is about 30

log = logging.getLogger("uvicorn.error")


class FindStations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    province: str | None = None
    district: str | None = None
    subdistrict: str | None = None
    frequency: float | None = None
    name: str | None = None
    source: Literal["ASMS", "WEB", "BCS", "BCS2", "BCS3", "OPER"] | None = None
    limit: int = Field(25, ge=1, le=100)
    details: bool = False


class CountStations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspected_from: date
    inspected_to: date
    province: str | None = None
    district: str | None = None
    result: Literal["ตรงตามมาตรฐาน", "ไม่ตรงตามมาตรฐาน"] | None = None  # the portal's OpinionDet


def create_app(
    make_api: Callable[[], NbtcOper] = NbtcOper, register_file: Path | None = None
) -> FastAPI:
    app = FastAPI(title="nbtc-oper", docs_url=None, redoc_url=None, openapi_url=None)
    api = None
    register_file = register_file or config.state_dir() / register.FILE_NAME
    saved = {"mtime": None, "copy": None}
    refresh = {"thread": None}
    # One portal session, one request at a time: Session keeps a cookie jar and
    # a min-interval clock that concurrent calls would trample.
    lock = threading.Lock()

    def portal() -> NbtcOper:
        nonlocal api
        if api is None:
            api = make_api()
        return api

    def saved_register() -> dict | None:
        """The register copy, re-read whenever its file changes."""
        mtime = register_file.stat().st_mtime if register_file.is_file() else None
        if mtime != saved["mtime"]:
            saved["mtime"], saved["copy"] = mtime, register.load(register_file) if mtime else None
        return saved["copy"]

    def rebuild(lock: register.BuildLock) -> None:
        # Its own portal session, so questions keep using the shared one meanwhile.
        try:
            copy = register.rebuild(make_api(), register_file, lock=lock, log=log.info)
            log.info("register rebuilt: %d station(s) %s", len(copy["stations"]), copy["counts"])
        except Exception:
            log.exception("register rebuild failed; the previous copy stays")

    def authorized(authorization: str | None = Header(None)) -> None:
        token = os.environ.get("OPER_API_TOKEN", "")
        if not token:
            raise HTTPException(500, "OPER_API_TOKEN is not set")
        if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "unauthorized")

    @app.exception_handler(CloudflareChallenge)
    def cloudflare(_, exc):
        return JSONResponse({"error": "cloudflare", "detail": str(exc)}, status_code=503)

    @app.exception_handler(LoginFailed)
    def login_failed(_, exc):
        return JSONResponse({"error": "login_failed", "detail": str(exc)}, status_code=502)

    @app.exception_handler(CredentialsNotFound)
    def no_credentials(_, exc):
        return JSONResponse({"error": "no_credentials", "detail": str(exc)}, status_code=500)

    @app.exception_handler(register.Busy)
    def busy(_, exc):
        return JSONResponse({"error": "busy", "detail": str(exc)}, status_code=409)

    @app.exception_handler(NbtcError)
    def portal_error(_, exc):
        return JSONResponse({"error": "portal", "detail": str(exc)}, status_code=502)

    @app.exception_handler(ValueError)
    def bad_input(_, exc):
        # UnknownPlace is a ValueError: the model can retry with a corrected name
        kind = "unknown_place" if isinstance(exc, UnknownPlace) else "bad_input"
        return JSONResponse({"error": kind, "detail": str(exc)}, status_code=400)

    @app.get("/health")
    def health():
        copy = saved_register()
        thread = refresh["thread"]
        return {
            "ok": True,
            "as_of": copy["built_at"] if copy else None,
            "refreshing": bool(thread and thread.is_alive()),
        }

    @app.post("/refresh", status_code=202, dependencies=[Depends(authorized)])
    def start_refresh():
        lock = register.BuildLock(register_file)
        lock.acquire()  # Busy -> 409: a running rebuild is refused, not queued
        refresh["thread"] = threading.Thread(target=rebuild, args=(lock,), daemon=True)
        refresh["thread"].start()
        return {"started": True}

    @app.post("/find-stations", dependencies=[Depends(authorized)])
    def find_stations(body: FindStations):
        args = body.model_dump(exclude_none=True)
        with lock:
            copy = saved_register()
            if copy is not None and register.covers(copy, portal().places(), **args):
                return register.find(copy, portal().places(), **args)
            if body.details:
                args["limit"] = min(body.limit, DETAILS_LIMIT)
            return portal().find_stations(**args, time_limit=LIVE_TIME_LIMIT)

    @app.post("/count-stations", dependencies=[Depends(authorized)])
    def count_stations(body: CountStations):
        if body.inspected_to < body.inspected_from:
            raise ValueError("inspected_to is before inspected_from")
        with lock:
            result = portal().count_stations(
                inspected_from=body.inspected_from.isoformat(),
                inspected_to=body.inspected_to.isoformat(),
                province=body.province,
                district=body.district,
                result=body.result,
            )
        return {
            **result,
            "inspected_from": body.inspected_from.isoformat(),
            "inspected_to": body.inspected_to.isoformat(),
        }

    return app


app = create_app()
