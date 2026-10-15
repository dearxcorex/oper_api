"""HTTP wrapper around NbtcOper for fm-station-tracker's Discord /ask bot.

Runs on a home machine because Cloudflare challenges the portal from cloud IPs
(Vercel included), and is reached through Tailscale Funnel. Read-only, and
never returns coordinates: only find_stations summaries and inspection counts.

    uv run --group server uvicorn server.app:app --host 127.0.0.1 --port 8787

Every route but /health needs `Authorization: Bearer $OPER_API_TOKEN`.
"""
import os
import secrets
import threading
from datetime import date
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from nbtc_oper import CloudflareChallenge, CredentialsNotFound, LoginFailed, NbtcError, NbtcOper
from nbtc_oper.places import UnknownPlace

DETAILS_LIMIT = 10  # details costs one portal request per station shown


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


def create_app(make_api: Callable[[], NbtcOper] = NbtcOper) -> FastAPI:
    app = FastAPI(title="nbtc-oper", docs_url=None, redoc_url=None, openapi_url=None)
    api = None
    # One portal session, one request at a time: Session keeps a cookie jar and
    # a min-interval clock that concurrent calls would trample.
    lock = threading.Lock()

    def portal() -> NbtcOper:
        nonlocal api
        if api is None:
            api = make_api()
        return api

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
        return {"ok": True}

    @app.post("/find-stations", dependencies=[Depends(authorized)])
    def find_stations(body: FindStations):
        args = body.model_dump(exclude_none=True)
        if body.details:
            args["limit"] = min(body.limit, DETAILS_LIMIT)
        with lock:
            return portal().find_stations(**args)

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
            )
        return {
            **result,
            "inspected_from": body.inspected_from.isoformat(),
            "inspected_to": body.inspected_to.isoformat(),
        }

    return app


app = create_app()
