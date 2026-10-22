"""GPU를 할당·제어하지 않는 내부 자원 관측 서비스."""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException

from ..host_resource_probe import read_host_resource_snapshot
from ..settings_parts.env import as_bool, is_default_secret


def create_host_resource_observer_app() -> FastAPI:
    required = as_bool(os.environ.get("INTERNAL_SERVICE_AUTH_REQUIRED"), False)
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "")
    if required and is_default_secret(token):
        raise RuntimeError(
            "Host resource observer requires a non-default internal token"
        )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/snapshot")
    async def snapshot(authorization: str | None = Header(default=None)):
        if required and not hmac.compare_digest(authorization or "", "Bearer " + token):
            raise HTTPException(401, detail="invalid internal service token")
        observation = await asyncio.to_thread(read_host_resource_snapshot)
        return {**asdict(observation), "observed_at": time.time()}

    return app
