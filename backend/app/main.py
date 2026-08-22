from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import auth, devices, metrics, alerts, notifications, upload, system, users, device_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register collectors
    import app.collectors.panos_api  # noqa: F401
    import app.collectors.panos_ssh  # noqa: F401
    import app.collectors.panorama  # noqa: F401
    import app.collectors.panos_report  # noqa: F401
    import app.collectors.file_upload  # noqa: F401

    # Startup: init DB, create admin user, load builtin metrics
    from app.models.database import init_db
    await init_db()
    yield
    # Shutdown: cleanup


app = FastAPI(
    title="NGFW Monitor API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["devices"])
app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["metrics"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(upload.router, prefix="/api/v1/upload", tags=["upload"])
app.include_router(system.router, prefix="/api/v1/system", tags=["system"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(device_groups.router, prefix="/api/v1/device-groups", tags=["device-groups"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
