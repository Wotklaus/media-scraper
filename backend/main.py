from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scraper import scrape_profile

app = FastAPI(title="Media Scraper API")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


# Retrieve TikTok profile information.
@app.get("/api/profile/{username}")
def get_profile(username: str):
    try:
        return scrape_profile(username)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))


# Serve the main web interface.
@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


# Serve frontend assets.
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
