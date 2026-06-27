import httpx
import json
import uuid
import time
import os
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from redis import Redis
from langfuse import Langfuse
from app.models import User, Tenant
from app.auth import get_current_user, require_role
from app.database import get_db

router = APIRouter(prefix="/chat", tags=["chat"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DEFAULT_HERMES_URL = os.getenv("HERMES_BASE_URL", "http://hermes-agent:8000")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://hermes_langfuse:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("hermes.api")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(f"{LOG_DIR}/api.log")
fh.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(fh)


def log(event: str, **kwargs):
    entry = {"timestamp": datetime.utcnow().isoformat(), "event": event, **kwargs}
    logger.info(json.dumps(entry))


def get_redis():
    return Redis.from_url(REDIS_URL, decode_responses=True)


def get_langfuse():
    if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
        return Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
    return None


def get_hermes_url(tenant: Tenant) -> str:
    if tenant.container_name:
        return f"http://{tenant.container_name}:8000"
    return DEFAULT_HERMES_URL


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    async_mode: bool = False


class ChatResponse(BaseModel):
    reply: str | None = None
    session_id: str | None = None
    job_id: str | None = None
    status: str = "done"


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    hermes_url = get_hermes_url(tenant)
    job_id = str(uuid.uuid4())
    langfuse = get_langfuse()

    log("chat_request",
        job_id=job_id,
        tenant=tenant.slug,
        user_id=str(current_user.id),
        async_mode=body.async_mode)

    # ── Async mode ────────────────────────────────────────────────────────
    if body.async_mode:
        redis = get_redis()
        job = {
            "job_id":         job_id,
            "tenant_slug":    tenant.slug,
            "tenant_id":      str(tenant.id),
            "user_id":        str(current_user.id),
            "user_role":      current_user.role,
            "message":        body.message,
            "session_id":     body.session_id,
            "hermes_url":     hermes_url,
            "container_name": tenant.container_name or "hermes_enterprise_agent",
        }
        redis.rpush("chat_jobs", json.dumps(job))
        log("job_enqueued", job_id=job_id, tenant=tenant.slug)
        return ChatResponse(job_id=job_id, status="queued")

    # ── Sync mode ─────────────────────────────────────────────────────────
    start = time.time()

    # Start Langfuse trace
    trace = None
    generation = None
    if langfuse:
        trace = langfuse.trace(
            name="chat",
            user_id=str(current_user.id),
            metadata={"tenant": tenant.slug, "job_id": job_id},
        )
        generation = trace.generation(
            name="hermes-response",
            model="gemini-2.5-flash",
            input=body.message,
        )

    headers = {
        "X-Tenant-ID":   str(current_user.tenant_id),
        "X-User-ID":     str(current_user.id),
        "X-User-Role":   current_user.role,
        "X-Tenant-Slug": tenant.slug,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{hermes_url}/chat",
                json={"message": body.message, "session_id": body.session_id},
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()
        reply = data.get("reply", "")
        latency = round(time.time() - start, 3)

        # Log to Langfuse
        if generation:
            generation.end(output=reply, metadata={"latency_seconds": latency})
        if langfuse:
            langfuse.flush()

        log("chat_completed", job_id=job_id, tenant=tenant.slug, latency_seconds=latency)
        return ChatResponse(
            reply=reply,
            session_id=data.get("session_id"),
            job_id=job_id,
            status="done"
        )

    except httpx.HTTPStatusError as e:
        if generation:
            generation.end(level="ERROR", status_message=str(e))
        log("chat_error", job_id=job_id, error=str(e))
        raise HTTPException(status_code=e.response.status_code, detail="Hermes agent error")
    except httpx.RequestError as e:
        if generation:
            generation.end(level="ERROR", status_message=str(e))
        log("chat_error", job_id=job_id, error=str(e))
        raise HTTPException(status_code=503, detail="Hermes agent unreachable")


@router.get("/result/{job_id}")
def get_result(job_id: str, current_user: User = Depends(get_current_user)):
    redis = get_redis()
    raw = redis.get(f"result:{job_id}")
    if not raw:
        return {"status": "pending", "job_id": job_id}
    return json.loads(raw)


@router.get("/history", dependencies=[Depends(require_role("admin", "user"))])
async def history(current_user: User = Depends(get_current_user)):
    return {
        "user": current_user.email,
        "tenant": current_user.tenant.slug,
        "history": []
    }
