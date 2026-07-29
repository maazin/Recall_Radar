import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DESCRIPTION = """
RecallRadar indexes food recalls and foodborne-illness outbreak investigations
published by the FDA, USDA/FSIS and CDC, and links back to the original agency
record for every entry.

RecallRadar is an aggregator. It does not issue health alerts and is not an
authoritative source. Always consult the linked agency record.
"""

app = FastAPI(
    title="RecallRadar API",
    description=DESCRIPTION,
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "RecallRadar API",
        "docs": "/docs",
        "disclaimer": (
            "Aggregator of FDA, USDA/FSIS and CDC published records. "
            "Not an alerting authority."
        ),
    }
