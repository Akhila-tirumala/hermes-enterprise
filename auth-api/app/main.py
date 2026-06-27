from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db, engine
from app.api.routers import auth, chat
from app.telemetry import setup_telemetry

app = FastAPI(
    title="Hermes Enterprise API",
    description="JWT-authenticated gateway in front of Hermes agents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup telemetry BEFORE routes are added
setup_telemetry(app, engine=engine)

app.include_router(auth.router)
app.include_router(chat.router)

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/health")
def health():
    return {"status": "ok"}
