"""Production entry point: original async engine, then the Media Scraper adapter."""
import asyncio
import logging
from playwright.async_api import Error as PlaywrightError
from .reference_adapter import adapt_profile
from .reference_runtime import USERNAME, AccessRestricted, IdentityError
from .vendor.scrapingtiktok.tiktok_scraper import TikTokScraper


async def extract_profile(username):
    engine = TikTokScraper(headless=True)
    try:
        raw = await engine.scrape(username, max_list_items=30, max_videos=10, max_comments_per_video=20)
        return adapt_profile(raw, username)
    except (AccessRestricted, IdentityError):
        raise
    except PlaywrightError:
        raise RuntimeError('No se pudo iniciar Chromium o cargar TikTok. Comprueba la sesión local y la conexión.') from None


def scrape_profile(username):
    username = username.strip().removeprefix('@')
    if not USERNAME.fullmatch(username):
        raise ValueError('Invalid TikTok username.')
    profile = asyncio.run(extract_profile(username))
    logging.getLogger(__name__).info('engine=SCRAPINGTIKTOK publications=%s recovered_comments=%s',
                                   len(profile['videos']), sum(len(video['comments_list']) for video in profile['videos']))
    return profile
