
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from scraper import scrape_profile

app = FastAPI(title="Media Scraper API")

# Allow requests from the local frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# Check API availability.
@app.get("/")
def home():
    return {"message": "Media Scraper API is running"}


# Retrieve TikTok profile information.
@app.get("/api/profile/{username}")
def get_profile(username: str):
    try:
        return scrape_profile(username)

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )
