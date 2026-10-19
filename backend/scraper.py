
import re

from playwright.sync_api import (
    sync_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)


# Add, remove, or update extraction fields here.
PROFILE_FIELDS = {
    "nickname": '[data-e2e="user-title"]',
    "followers": '[data-e2e="followers-count"]',
    "following": '[data-e2e="following-count"]',
    "likes": '[data-e2e="likes-count"]',
    "bio": '[data-e2e="user-bio"]',
}


# Validate the TikTok username.
def validate_username(username):
    username = username.strip().removeprefix("@")

    if not re.fullmatch(r"[A-Za-z0-9._]{1,24}", username):
        raise ValueError("Invalid TikTok username.")

    return username


# Extract text from a page element.
def get_element_text(page, selector):
    try:
        return page.locator(selector).first.inner_text(
            timeout=5000
        ).strip()
    except PlaywrightTimeoutError:
        return None


# Extract all configured profile fields.
def extract_profile_data(page, username):
    profile = {
        "username": username,
        "url": page.url,
    }

    for field, selector in PROFILE_FIELDS.items():
        profile[field] = get_element_text(page, selector)

    return profile


# Open Chromium and retrieve public profile data.
def scrape_profile(username):
    username = validate_username(username)
    url = f"https://www.tiktok.com/@{username}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False
            )

            try:
                page = browser.new_page()

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                if response is None or response.status != 200:
                    raise RuntimeError(
                        "Unable to access the TikTok profile."
                    )

                # Wait for the profile to load.
                try:
                    page.locator(
                        PROFILE_FIELDS["nickname"]
                    ).first.wait_for(timeout=15000)
                except PlaywrightTimeoutError:
                    pass

                return extract_profile_data(page, username)

            finally:
                browser.close()

    except PlaywrightError as error:
        raise RuntimeError(str(error)) from error
