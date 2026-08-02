"""
FastAPI Application Entry Point
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, environments, audit, teams, users, health
from app.services import health_checker

logger = logging.getLogger("idplite.main")


# --- Background Health Polling ---
# Polls CloudWatch/ECS every 5 minutes for all RUNNING environments and
# updates health_status / health_checked_at. Started as an asyncio task on
# app startup rather than a separate process/cron — this is a portfolio
# project running a single API instance, so an in-process background task
# is the simplest thing that works. At scale this would move to its own
# worker.
@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(health_checker.poll_health_forever())
    logger.info("Health poller started (interval=%ss)", health_checker.DEFAULT_POLL_INTERVAL_SECONDS)

    yield

    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
    logger.info("Health poller stopped")


app = FastAPI(
    title="IDP Lite API",
    version="0.1.0",
    description="Self-service Internal Developer Platform — provision cloud environments on demand.",
    lifespan=lifespan,
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Vite dev server
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Router Registration ---
app.include_router(auth.router,         prefix="/auth",         tags=["auth"])
app.include_router(environments.router, prefix="/environments", tags=["environments"])
app.include_router(audit.router,        prefix="/audit",        tags=["audit"])
app.include_router(teams.router,        prefix="/teams",        tags=["teams"])
app.include_router(users.router,        prefix="/users",        tags=["users"])
app.include_router(health.router,                               tags=["health"])