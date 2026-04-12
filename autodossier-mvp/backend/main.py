"""AutoDossier MVP – FastAPI entry point"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import vin as vin_router
from routers import carfax as carfax_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

app = FastAPI(
    title="AutoDossier API",
    description="Free VIN lookup & vehicle cost report",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(vin_router.router, prefix="/api")
app.include_router(carfax_router.router, prefix="/api")


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "AutoDossier API"}


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
