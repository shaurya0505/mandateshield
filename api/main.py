import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router

app = FastAPI(
    title="MandateShield: Autonomous Mandate Recovery Engine",
    description="Intelligent Recurring Payment Recovery & Safety Guardian for India Subscriptions",
    version="1.0.0",
)

# Enable CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Mount UI static directory
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

@app.get("/")
def serve_index():
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "service": "MandateShield Command Center API",
        "status": "online",
        "docs": "/docs",
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "MandateShield"}
