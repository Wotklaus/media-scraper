
import json
import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    sync_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

PROFILE_FIELDS = {
    "nickname": '[data-e2e="user-title"]',
    "followers": '[data-e2e="followers-count"]',
    "following": '[data-e2e="following-count"]',
    "likes": '[data-e2e="likes-count"]',
    "bio": '[data-e2e="user-bio"]',
}

AVATAR_SELECTOR = (
    '[data-e2e="user-avatar"] img, '
    'img[data-e2e="user-avatar"]'
)

VIDEO_LINK_SELECTOR = 'a[href*="/video/"]'

USER_LIST_SELECTORS = {
    "followers": [
        '[data-e2e="followers-count"]',
        '[data-e2e="followers"]',
    ],
    "following": [
        '[data-e2e="following-count"]',
        '[data-e2e="following"]',
    ],
}

USER_DIALOG_SELECTORS = [
    '[role="dialog"]',
    '[data-e2e="follow-info-popup"]',
    '[class*="DivUserListContainer"]',
]

COMMENT_SELECTORS = [
    '[data-e2e="comment-level-1"]',
    '[data-e2e="comment-item"]',
]

COMMENT_TEXT_SELECTORS = [
    '[data-e2e="comment-text"]',
    '[data-e2e="comment-content"]',
]

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,24}$")


def validate_username(username):
    username = username.strip().removeprefix("@")

    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Invalid TikTok username.")

    return username


def get_element_text(page, selector, timeout=3000):
    try:
        return page.locator(selector).first.inner_text(
            timeout=timeout
        ).strip()
    except PlaywrightTimeoutError:
        return None


def format_metric(value):
    if value is None:
        return "N/A"

    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return str(value)


def get_avatar_url(page):
    try:
        image = page.locator(AVATAR_SELECTOR).first
        image.wait_for(state="attached", timeout=5000)

        source = image.get_attribute("src")

        if source and source.startswith("http"):
            return source

    except PlaywrightTimeoutError:
        pass

    return None


def get_embedded_json(page):
    selectors = [
        "script#__UNIVERSAL_DATA_FOR_REHYDRATION__",
        "script#SIGI_STATE",
        "script#__NEXT_DATA__",
    ]

    for selector in selectors:
        try:
            content = page.locator(selector).first.text_content(
                timeout=3000
            )

            if content:
                return json.loads(content)

        except (PlaywrightTimeoutError, ValueError):
            continue

    return None


def find_video_payload(data):
    if isinstance(data, dict):
        item = data.get("itemStruct")

        if isinstance(item, dict):
            stats = item.get("stats")

            if isinstance(stats, dict):
                return item

        stats = data.get("stats")

        if isinstance(stats, dict) and any(
                key in stats
                for key in (
                        "playCount",
                        "diggCount",
                        "commentCount",
                        "shareCount",
                        "collectCount",
                )
        ):
            return data

        for value in data.values():
            result = find_video_payload(value)

            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_video_payload(item)

            if result:
                return result

    return None


def extract_profile_data(page, username):
    profile = {
        "username": username,
        "url": page.url,
    }

    for field, selector in PROFILE_FIELDS.items():
        profile[field] = get_element_text(page, selector)

    profile["avatar_url"] = get_avatar_url(page)

    return profile


# Read a username from a public profile link.
def username_from_href(href):
    if not href:
        return None

    parsed = urlparse(urljoin("https://www.tiktok.com", href))

    if parsed.hostname not in {
        "www.tiktok.com",
        "tiktok.com",
    }:
        return None

    match = re.fullmatch(
        r"/@([A-Za-z0-9._]{1,24})/?",
        parsed.path,
    )

    if not match:
        return None

    return match.group(1)


# Find a visible user-list dialog.
def find_user_dialog(page):
    for selector in USER_DIALOG_SELECTORS:
        dialog = page.locator(selector)

        try:
            for index in range(min(dialog.count(), 5)):
                item = dialog.nth(index)

                if item.is_visible():
                    return item

        except PlaywrightError:
            continue

    return None


# Collect usernames from an opened dialog.
def read_usernames(dialog, limit=10):
    usernames = []
    seen = set()

    links = dialog.locator('a[href*="/@"]')

    for index in range(min(links.count(), 100)):
        href = links.nth(index).get_attribute("href")
        username = username_from_href(href)

        if not username:
            continue

        key = username.lower()

        if key in seen:
            continue

        seen.add(key)
        usernames.append(username)

        if len(usernames) >= limit:
            break

    return usernames


# Try to read public followers or following.
def extract_user_list(page, list_type, limit=10):
    selectors = USER_LIST_SELECTORS.get(list_type, [])

    for selector in selectors:
        trigger = page.locator(selector).first

        try:
            if not trigger.is_visible(timeout=2000):
                continue

            trigger.click(timeout=5000)

            # Wait for the list to appear.
            try:
                page.locator(
                    ", ".join(USER_DIALOG_SELECTORS)
                ).first.wait_for(
                    state="visible",
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                pass

            dialog = find_user_dialog(page)

            if dialog is None:
                print(f"{list_type}: No public user list found.")
                page.keyboard.press("Escape")
                return []

            usernames = read_usernames(dialog, limit=limit)

            print(f"{list_type}: {len(usernames)} usernames found.")

            page.keyboard.press("Escape")

            return usernames

        except PlaywrightError:
            try:
                page.keyboard.press("Escape")
            except PlaywrightError:
                pass

    print(f"{list_type}: User list unavailable.")
    return []


# Collect up to 10 public video links.
def get_profile_video_cards(page, limit=10):
    videos = []
    seen = set()

    try:
        page.locator(VIDEO_LINK_SELECTOR).first.wait_for(
            state="attached",
            timeout=10000,
        )

    except PlaywrightTimeoutError:
        return videos

    locator = page.locator(VIDEO_LINK_SELECTOR)

    for index in range(min(locator.count(), 40)):
        item = locator.nth(index)
        href = item.get_attribute("href")

        if not href:
            continue

        url = urljoin("https://www.tiktok.com", href)
        parsed = urlparse(url)

        if parsed.hostname not in {
            "tiktok.com",
            "www.tiktok.com",
        }:
            continue

        match = re.search(r"/video/(\d+)", parsed.path)

        if not match:
            continue

        video_id = match.group(1)

        if video_id in seen:
            continue

        seen.add(video_id)

        preview_url = None

        try:
            preview_url = item.locator("img").first.get_attribute(
                "src",
                timeout=1500,
            )
        except PlaywrightError:
            pass

        videos.append(
            {
                "id": video_id,
                "url": url.split("?")[0],
                "preview_url": preview_url,
            }
        )

        if len(videos) >= limit:
            break

    return videos


# Find comment items currently visible in the DOM.
def find_comment_items(page):
    for selector in COMMENT_SELECTORS:
        locator = page.locator(selector)

        if locator.count() > 0:
            return locator

    return None


# Read the text of one comment.
def read_comment_text(item):
    for selector in COMMENT_TEXT_SELECTORS:
        locator = item.locator(selector).first

        try:
            if locator.count() > 0:
                text = locator.inner_text(timeout=1500).strip()

                if text:
                    return text

        except PlaywrightError:
            continue

    return None


# Extract visible comment authors and texts.
def extract_video_comments(page, limit=10):
    comments = []
    seen = set()

    try:
        page.locator(
            ", ".join(COMMENT_SELECTORS)
        ).first.wait_for(
            state="attached",
            timeout=5000,
        )

    except PlaywrightTimeoutError:
        return comments

    items = find_comment_items(page)

    if items is None:
        return comments

    for index in range(min(items.count(), 60)):
        item = items.nth(index)
        username = None

        links = item.locator('a[href*="/@"]')

        for link_index in range(min(links.count(), 10)):
            href = links.nth(link_index).get_attribute("href")
            username = username_from_href(href)

            if username:
                break

        text = read_comment_text(item)

        if not username or not text:
            continue

        key = (username.lower(), text)

        if key in seen:
            continue

        seen.add(key)

        comments.append(
            {
                "username": username,
                "text": text,
            }
        )

        if len(comments) >= limit:
            break

    return comments


# Extract video metrics and available public comments.
def extract_video_details(page, video_url, fallback_preview=None):
    payload = get_embedded_json(page)
    item = find_video_payload(payload) if payload else None

    result = {
        "url": video_url,
        "preview_url": fallback_preview,
        "title": "Not available",
        "views": "N/A",
        "likes": "N/A",
        "comments": "N/A",
        "shares": "N/A",
        "saves": "N/A",
        "comments_list": [],
    }

    if item:
        stats = item.get("stats") or {}
        video_info = item.get("video") or {}

        result.update(
            {
                "preview_url": (
                        fallback_preview
                        or video_info.get("cover")
                        or video_info.get("originCover")
                        or video_info.get("dynamicCover")
                ),
                "title": (
                        item.get("desc")
                        or "Video without description"
                ),
                "views": format_metric(stats.get("playCount")),
                "likes": format_metric(stats.get("diggCount")),
                "comments": format_metric(stats.get("commentCount")),
                "shares": format_metric(stats.get("shareCount")),
                "saves": format_metric(stats.get("collectCount")),
            }
        )

    result["comments_list"] = extract_video_comments(
        page,
        limit=10,
    )

    return result


# Open each video and read available details.
def extract_latest_videos(context, video_cards):
    results = []

    for number, card in enumerate(video_cards, start=1):
        video_page = context.new_page()

        result = {
            "id": card["id"],
            "url": card["url"],
            "preview_url": card.get("preview_url"),
            "title": "Not available",
            "views": "N/A",
            "likes": "N/A",
            "comments": "N/A",
            "shares": "N/A",
            "saves": "N/A",
            "comments_list": [],
        }

        try:
            response = video_page.goto(
                card["url"],
                wait_until="domcontentloaded",
                timeout=30000,
            )

            if response and response.status == 200:
                details = extract_video_details(
                    video_page,
                    card["url"],
                    card.get("preview_url"),
                )

                result.update(details)

            print(
                f"Video {number}: "
                f"{len(result['comments_list'])} comments found."
            )

        except PlaywrightError as error:
            print(f"Video {number}: {error}")

        finally:
            video_page.close()

        results.append(result)

    return results


# Retrieve a public profile and its available details.
def scrape_profile(username):
    username = validate_username(username)
    url = f"https://www.tiktok.com/@{username}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False
            )

            try:
                context = browser.new_context()
                page = context.new_page()

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                if response is None or response.status != 200:
                    raise RuntimeError(
                        "Unable to access the TikTok profile."
                    )

                try:
                    page.locator(
                        PROFILE_FIELDS["nickname"]
                    ).first.wait_for(
                        state="visible",
                        timeout=15000,
                    )

                except PlaywrightTimeoutError:
                    pass

                profile = extract_profile_data(
                    page,
                    username,
                )

                # Read public profile user lists.
                profile["followers_users"] = extract_user_list(
                    page,
                    "followers",
                    limit=10,
                )

                profile["following_users"] = extract_user_list(
                    page,
                    "following",
                    limit=10,
                )

                # Wait for public video links.
                try:
                    page.locator(
                        VIDEO_LINK_SELECTOR
                    ).first.wait_for(
                        state="attached",
                        timeout=20000,
                    )

                except PlaywrightTimeoutError:
                    print("Video links unavailable.")

                video_cards = get_profile_video_cards(
                    page,
                    limit=10,
                )

                print(
                    f"Video cards found: {len(video_cards)}"
                )

                profile["videos"] = extract_latest_videos(
                    context,
                    video_cards,
                )

                return profile

            finally:
                browser.close()

    except PlaywrightError as error:
        raise RuntimeError(str(error)) from error
