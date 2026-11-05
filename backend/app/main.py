from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .routers import auth, compliance, dashboard, dispatch, fleet, loading, system


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LogiTrack API",
        version=__version__,
        description="Logistics operations API: fleet, bays, dispatch and turnaround analytics.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(fleet.router)
    app.include_router(loading.router)
    app.include_router(dispatch.router)
    app.include_router(compliance.router)
    return app


app = create_app()
