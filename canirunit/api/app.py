from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from canirunit import __version__
from canirunit.config import Settings, get_settings
from canirunit.hardware.base import HardwareDetector, HardwareProfile
from canirunit.resources import resource_dir


def create_app(detector: HardwareDetector, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="CanIRunIt", version=__version__)
    state: dict[str, HardwareProfile] = {}

    def scan() -> HardwareProfile:
        try:
            profile = detector.detect()
        except Exception as exc:  # detection failure must surface as a clean API error
            raise HTTPException(status_code=500, detail=f"Hardware scan failed: {exc}") from exc
        state["hw"] = profile
        return profile

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__, "has_api_key": settings.has_api_key}

    @app.get("/api/hardware")
    def hardware() -> HardwareProfile:
        return state.get("hw") or scan()

    @app.post("/api/hardware/rescan")
    def rescan() -> HardwareProfile:
        return scan()

    ui_dir = resource_dir("ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(ui_dir / "index.html")

    app.mount("/static", StaticFiles(directory=ui_dir), name="static")
    return app
