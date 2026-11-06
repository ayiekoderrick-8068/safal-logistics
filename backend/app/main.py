from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .deps import require_workspace
from .middleware import SecurityHeadersMiddleware
from .models import Workspace
from .routers import (
    alerts,
    analytics,
    auth,
    compliance,
    dashboard,
    dispatch,
    fleet,
    incidents,
    loading,
    maintenance,
    maintenance_equipment,
    maintenance_parts,
    maintenance_pm,
    maintenance_work,
    reports,
    system,
    users,
)

# Each session is bound to one workspace; these guards make the API refuse the other one.
LOGISTICS = [Depends(require_workspace(Workspace.LOGISTICS))]
MAINTENANCE = [Depends(require_workspace(Workspace.MAINTENANCE))]


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="LogiTrack API",
        version=__version__,
        description="Logistics operations API: fleet, bays, dispatch and turnaround analytics.",
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.add_middleware(SecurityHeadersMiddleware)  # outermost: also covers CORS/413 replies
    # Shared by both workspaces: health/meta, authentication, user administration (admin-only).
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    # Logistics Operations
    for module in (
        dashboard,
        fleet,
        loading,
        dispatch,
        compliance,
        incidents,
        alerts,
        analytics,
        reports,
    ):
        app.include_router(module.router, dependencies=LOGISTICS)
    # Maintenance Operations
    for module in (
        maintenance,
        maintenance_equipment,
        maintenance_pm,
        maintenance_work,
        maintenance_parts,
    ):
        app.include_router(module.router, dependencies=MAINTENANCE)
    return app


app = create_app()
