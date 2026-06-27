import os
import json
import time
import logging
import subprocess
from redis import Redis
from datetime import datetime

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
QUEUE_NAME = "chat_jobs"
LOG_DIR = "/app/logs"

os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("hermes.worker")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(f"{LOG_DIR}/worker.log")
file_handler.setFormatter(logging.Formatter('%(message)s'))
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def log(event: str, **kwargs):
    entry = {"timestamp": datetime.utcnow().isoformat(), "event": event, **kwargs}
    logger.info(json.dumps(entry))


def process_job(redis: Redis, job: dict):
    job_id      = job.get("job_id")
    tenant_slug = job.get("tenant_slug")
    user_id     = job.get("user_id")
    message     = job.get("message")
    session_id  = job.get("session_id")
    container   = job.get("container_name", "hermes_enterprise_agent")

    start = time.time()
    log("job_started", job_id=job_id, tenant=tenant_slug, user_id=user_id)

    try:
        cmd = [
            "docker", "exec", container,
            "./hermes-agent/hermes", "chat",
            "-q", message,
            "-Q",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        latency = round(time.time() - start, 3)

        if result.returncode == 0:
            reply = result.stdout.strip()
            log("job_completed",
                job_id=job_id,
                tenant=tenant_slug,
                latency_seconds=latency,
                reply_length=len(reply))
            redis.setex(f"result:{job_id}", 300,
                json.dumps({"status": "done", "reply": reply, "session_id": session_id}))
        else:
            error = result.stderr.strip()
            log("job_failed", job_id=job_id, tenant=tenant_slug,
                error=error[:200], latency_seconds=latency)
            redis.setex(f"result:{job_id}", 300,
                json.dumps({"status": "error", "error": error[:200]}))

    except subprocess.TimeoutExpired:
        log("job_timeout", job_id=job_id, tenant=tenant_slug)
        redis.setex(f"result:{job_id}", 300,
            json.dumps({"status": "error", "error": "Request timed out after 120s"}))
    except Exception as e:
        log("job_error", job_id=job_id, error=str(e))
        redis.setex(f"result:{job_id}", 300,
            json.dumps({"status": "error", "error": str(e)}))


def main():
    log("worker_started", queue=QUEUE_NAME, redis_url=REDIS_URL)
    redis = Redis.from_url(REDIS_URL, decode_responses=True)

    while True:
        try:
            item = redis.blpop(QUEUE_NAME, timeout=5)
            if item:
                _, raw = item
                job = json.loads(raw)
                process_job(redis, job)
        except Exception as e:
            log("worker_error", error=str(e))
            time.sleep(2)


if __name__ == "__main__":
    main()
