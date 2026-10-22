from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .scraper import scrape_profile
from .demo import CaptureNotFoundError, load_capture
from .session import SessionBusyError
from .presentation import print_profile
from .repository import PersistenceError, save_profile
from .embedding_routes import router as embedding_router
from .stored_profiles import router as stored_profiles_router
from .semantic_routes import router as semantic_router

app = FastAPI(title="Media Scraper API")
app.include_router(embedding_router)
app.include_router(stored_profiles_router)
app.include_router(semantic_router)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


# Retrieve TikTok profile information.
@app.get("/api/profile/{username}")
def get_profile(username: str, mode: Literal["real", "demo"] = "real"):
    try:
        profile = load_capture(username) if mode == "demo" else scrape_profile(username)
        if mode == "real":
            save_profile(profile)
        print_profile(profile)
        return profile
    except PersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except SessionBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except CaptureNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))
    except OSError:
        raise HTTPException(status_code=503, detail="No se pudo acceder a los datos locales de Media Scraper.") from None


# Serve the main web interface.
@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


# Serve frontend assets.
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
