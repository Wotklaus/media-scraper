
import json
import logging
import re
from time import monotonic, time
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from .session import persistent_context

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

PROFILE_GRID_SELECTOR = '[data-e2e="user-post-item-list"]'
VIDEO_LINK_SELECTOR = ", ".join(
    f'{PROFILE_GRID_SELECTOR} {anchor}[href*="/{kind}/"]'
    for anchor in ('[data-e2e="user-post-item"] a', 'a[data-e2e="user-post-item"]')
    for kind in ("video", "photo")
)

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


class TikTokPageError(RuntimeError):
    """The requested TikTok content is not accessible on this page."""


def validate_content_page(page):
    """Reject known access screens without treating ordinary login buttons as gates."""
    path = urlparse(page.url).path.lower()
    if re.search(r"/(login|signup)(/|$)", path):
        raise TikTokPageError("TikTok solicita iniciar sesión o la sesión venció. Ejecuta: .venv/bin/python -m backend.manage session")
    if re.search(r"/(captcha|verify|challenge)(/|$)", path):
        raise TikTokPageError("TikTok solicita verificación (CAPTCHA). Ejecuta la configuración de sesión y comprueba manualmente el acceso.")

    screens = {
        "verification": (
            '[id*="captcha"], [class*="captcha"], '
            'iframe[src*="captcha"], iframe[src*="verify"]'
        ),
        "login": '[data-e2e="login-modal"], [data-e2e="login-dialog"]',
        "unavailable content": (
            '[data-e2e="video-unavailable"], [data-e2e="user-not-found"], '
            '[data-e2e="error-page"]'
        ),
    }
    for reason, selector in screens.items():
        for element in page.locator(selector).all():
            if element.is_visible():
                messages = {
                    "verification": "TikTok solicita verificación (CAPTCHA). Abre la configuración de sesión para comprobar el acceso manualmente.",
                    "login": "TikTok solicita login o la sesión venció. Ejecuta: .venv/bin/python -m backend.manage session",
                    "unavailable content": "El contenido solicitado no está disponible en TikTok.",
                }
                raise TikTokPageError(messages[reason])

    # Exact messages avoid matching descriptions, comments or navigation labels.
    for message in (
        "Video currently unavailable", "This video is unavailable",
        "Couldn't find this account", "Account not found",
        "Video no disponible", "No se pudo encontrar esta cuenta",
    ):
        for element in page.get_by_text(message, exact=True).all():
            if element.is_visible():
                raise TikTokPageError("El contenido solicitado no está disponible en TikTok.")


def get_embedded_json(page):
    """Read every available supported hydration block, including duplicates."""
    selector = (
        "script#__UNIVERSAL_DATA_FOR_REHYDRATION__, "
        "script#SIGI_STATE, script#__NEXT_DATA__"
    )
    try:
        page.locator(selector).first.wait_for(state="attached", timeout=5000)
    except PlaywrightTimeoutError:
        return []

    payloads = []
    for script in page.locator(selector).all():
        try:
            content = script.text_content(timeout=3000)
            if content:
                payloads.append(json.loads(content))
        except (PlaywrightTimeoutError, ValueError):
            continue
    return payloads


def find_video_payload(data, video_id):
    """Find metrics belonging to the requested video, never a recommendation."""
    if isinstance(data, dict):
        stats = data.get("stats")
        if (
            str(data.get("id", "")) == str(video_id)
            and isinstance(stats, dict)
            and any(key in stats for key in (
                "playCount", "diggCount", "commentCount", "shareCount",
                "collectCount",
            ))
        ):
            return data
        for value in data.values():
            result = find_video_payload(value, video_id)
            if result is not None:
                return result
    elif isinstance(data, list):
        for value in data:
            result = find_video_payload(value, video_id)
            if result is not None:
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
                logging.getLogger(__name__).debug(f"{list_type}: No public user list found.")
                page.keyboard.press("Escape")
                return []

            usernames = read_usernames(dialog, limit=limit)

            logging.getLogger(__name__).debug(f"{list_type}: {len(usernames)} usernames found.")

            page.keyboard.press("Escape")

            return usernames

        except PlaywrightError:
            try:
                page.keyboard.press("Escape")
            except PlaywrightError:
                pass

    logging.getLogger(__name__).debug(f"{list_type}: User list unavailable.")
    return []


# Collect up to 10 public video links.
def get_profile_video_cards(page, limit=10, username=None, expected_author=None, warnings=None):
    videos = []
    seen = set()
    if expected_author is None:
        expected_author = {"uniqueId": username or username_from_href(page.url)}
    allowed_authors = {str(value).casefold() for value in expected_author.values() if value}
    validate_content_page(page)

    try:
        page.locator(VIDEO_LINK_SELECTOR).first.wait_for(
            state="attached",
            timeout=10000,
        )

    except PlaywrightTimeoutError:
        validate_content_page(page)
        if warnings is not None:
            warnings.append("TikTok no entregó enlaces /video/ o /photo/ en las tarjetas de la cuadrícula; no se usaron recomendaciones.")
        return videos

    validate_content_page(page)
    locator = page.locator(VIDEO_LINK_SELECTOR)

    for index in range(locator.count()):
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

        match = re.fullmatch(r"/@([^/]+)/(video|photo)/(\d+)/?", parsed.path)

        if parsed.scheme != "https" or not match:
            continue
        if match.group(1).casefold() not in allowed_authors:
            if warnings is not None:
                warnings.append(f"Publicación {match.group(3)} descartada: el enlace no corresponde al usuario solicitado ni a sus identificadores confirmados.")
            continue

        video_id = match.group(3)

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
                "type": match.group(2),
                "url": url,
                "preview_url": preview_url,
            }
        )

        if limit is not None and len(videos) >= limit:
            break

    return videos


class CommentResponseCapture:
    """Observe browser responses only; never issue or replay requests.

    Association requires a single numeric aweme_id on the list request.
    The manually reported schema did not establish that identifier: responses
    without it are rejected until a real capture establishes another mapping.
    """

    def __init__(self, publication_id):
        self.publication_id = str(publication_id)
        self.comments = []
        self.seen = set()
        self.empty = False
        self.issues = []
        self.diagnostics = {}

    def note(self, reason):
        self.diagnostics[reason] = self.diagnostics.get(reason, 0) + 1

    def on_response(self, response):
        parsed = urlparse(response.url)
        if "comment/list" not in parsed.path:
            return
        self.note("candidate")
        if parsed.scheme != "https" or parsed.hostname not in {"www.tiktok.com", "tiktok.com"}:
            self.note("discard_host")
            return
        if parsed.path.rstrip("/") != "/api/comment/list":
            self.note("discard_path")
            return
        ids = parse_qs(parsed.query, keep_blank_values=True).get("aweme_id", [])
        if len(ids) != 1 or not ids[0].isdigit():
            self.note("discard_aweme_id")
            self.issues.append("Respuesta comment/list sin aweme_id único verificable; se ignoró.")
            return
        if ids[0] != self.publication_id:
            self.note("other_publication")
            return
        self.note("matched_publication")
        try:
            if response.status != 200:
                self.note("discard_http")
                self.issues.append("Falló la respuesta HTTP de comment/list.")
                return
            data = response.json()
        except (PlaywrightError, ValueError):
            self.note("discard_json")
            self.issues.append("No se pudo leer el JSON de comment/list.")
            return
        if (not isinstance(data, dict) or type(data.get("status_code")) is not int
                or data["status_code"] != 0 or not isinstance(data.get("comments"), list)):
            self.note("discard_structure")
            self.issues.append("Respuesta comment/list fallida o con estructura inválida.")
            return
        if "aweme_id" in data and str(data["aweme_id"]) != self.publication_id:
            self.note("discard_aweme_id")
            self.issues.append("Respuesta comment/list con identificador contradictorio; se ignoró.")
            return
        total, cursor, more = (data.get(key) for key in ("total", "cursor", "has_more"))
        if (type(total) is not int or total < 0 or type(cursor) is not int or cursor < 0
                or type(more) not in (int, bool) or more not in (0, 1)):
            self.note("discard_structure")
            self.issues.append("Respuesta comment/list con paginación o total inválidos.")
            return
        self.note("valid_structure")
        if not data["comments"]:
            if total == 0 and cursor == 0 and not more:
                self.empty = True
            else:
                self.issues.append("Comentarios no disponibles: comment/list no entregó elementos aunque no confirma total cero.")
            return
        if total == 0:
            self.note("discard_structure")
            self.issues.append("Respuesta comment/list con lista y total contradictorios.")
            return
        for entry in data["comments"][:100]:
            if len(self.comments) >= 10:
                break
            if not isinstance(entry, dict):
                self.note("discard_structure")
                self.issues.append("Comentario con estructura inválida omitido.")
                continue
            if "aweme_id" in entry and str(entry["aweme_id"]) != self.publication_id:
                self.note("discard_aweme_id")
                self.issues.append("Comentario de otra publicación omitido.")
                continue
            user = entry.get("user")
            names = [user[key] for key in ("unique_id", "uniqueId") if key in user] if isinstance(user, dict) else []
            text = entry.get("text")
            if (not names or any(not isinstance(name, str) or not USERNAME_PATTERN.fullmatch(name) for name in names)
                    or len({name.casefold() for name in names}) != 1
                    or not isinstance(text, str) or not text.strip()):
                self.note("discard_structure")
                self.issues.append("Comentario sin username o texto verificables omitido.")
                continue
            comment = {"username": names[0], "text": text.strip()}
            cid = entry.get("cid")
            if isinstance(cid, (str, int)) and not isinstance(cid, bool) and str(cid).isdigit():
                comment["cid"] = str(cid)
            key = ("cid", comment["cid"]) if "cid" in comment else ("text", names[0].casefold(), comment["text"])
            if key in self.seen:
                continue
            self.seen.add(key)
            for field in ("create_time", "digg_count", "reply_comment_total"):
                value = entry.get(field)
                if type(value) is int and value >= 0:
                    comment[field] = value
            language = entry.get("comment_language")
            if isinstance(language, str) and language.strip():
                comment["comment_language"] = language
            if len(self.comments) < 10:
                self.comments.append(comment)


def extract_video_comments(page, limit=10, warnings=None, expected_count=None, capture=None):
    """Prefer associated browser JSON, with a DOM fallback in a shared 3 s budget."""
    limit = max(0, min(limit, 10))
    if not limit:
        return []
    owned = capture is None
    if owned:
        match = re.fullmatch(r"/@[^/]+/(?:video|photo)/(\d+)/?", urlparse(page.url).path)
        capture = CommentResponseCapture(match.group(1) if match else "")
        page.on("response", capture.on_response)
    deadline = monotonic() + 3
    panel_state = "not_requested"

    def remaining(cap=3000):
        return max(1, min(cap, int((deadline - monotonic()) * 1000)))

    def panel_visible():
        return page.locator(", ".join(f"{selector}:visible" for selector in COMMENT_SELECTORS)).count() > 0

    try:
        validate_content_page(page)
        if not capture.comments and not capture.empty:
            if panel_visible():
                panel_state = "visible"
            else:
                trigger = page.locator('[data-e2e="comment-icon"]').first
                try:
                    trigger.wait_for(state="visible", timeout=remaining(1200))
                except PlaywrightTimeoutError:
                    panel_state = "button_unavailable"
                    capture.issues.append("El botón público de comentarios no apareció visible dentro del plazo.")
                else:
                    # trial checks actionability without clicking; never force a click.
                    try:
                        validate_content_page(page)
                        trigger.click(trial=True, timeout=remaining(500))
                        trigger.click(timeout=remaining(500))
                        panel_state = "clicked_unconfirmed"
                        validate_content_page(page)
                    except PlaywrightError:
                        panel_state = "click_failed"
                        capture.issues.append("Falló el clic del botón público de comentarios o no fue accionable.")
            while not capture.comments and not capture.empty and monotonic() < deadline:
                if panel_visible():
                    panel_state = "visible"
                    break
                page.wait_for_timeout(remaining(100))
                validate_content_page(page)
        if capture.comments:
            if panel_state == "clicked_unconfirmed":
                panel_state = "confirmed_by_response"
            return capture.comments[:limit]
        if capture.empty and not capture.issues:
            if panel_state == "clicked_unconfirmed":
                panel_state = "confirmed_by_response"
            logging.getLogger(__name__).debug("comment/list confirmó cero comentarios para %s", capture.publication_id)
            return []
        # Defer fallback warnings: a response may arrive during DOM reads.
        dom_warnings = []
        dom_comments = _extract_dom_comments(page, limit, dom_warnings, expected_count,
                                            timeout=remaining(), log_warnings=False)
        if capture.comments:
            if panel_state == "clicked_unconfirmed":
                panel_state = "confirmed_by_response"
            return capture.comments[:limit]
        if capture.empty and not capture.issues:
            return []
        if dom_comments:
            panel_state = "visible"
        elif panel_state == "clicked_unconfirmed":
            capture.issues.append("El clic se completó, pero no se confirmó la apertura ni se cargaron comentarios públicos.")
        for message in dom_warnings:
            logging.getLogger(__name__).warning(message)
        if warnings is not None:
            warnings.extend(dom_warnings)
        return dom_comments
    except (PlaywrightError, TikTokPageError) as error:
        reason = str(error) if isinstance(error, TikTokPageError) else "falló la lectura de comentarios"
        capture.issues.append(reason)
        return capture.comments[:limit]
    finally:
        if owned:
            page.remove_listener("response", capture.on_response)
        safe_id = capture.publication_id if capture.publication_id.isdigit() else "no verificable"
        logging.getLogger(__name__).debug(
            "Comentarios de %s: panel=%s; red=%s", safe_id, panel_state, capture.diagnostics,
        )
        for issue in dict.fromkeys(capture.issues):
            message = f"Comentarios de {safe_id}: {issue}"
            logging.getLogger(__name__).warning(message)
            if warnings is not None:
                warnings.append(message)


# Keep the existing selectors until a real individual-comment DOM is verified.
def find_comment_items(page):
    locator = page.locator(", ".join(COMMENT_SELECTORS))
    return locator if locator.count() else None


def read_comment_text(item):
    for selector in COMMENT_TEXT_SELECTORS:
        locator = item.locator(selector).first
        try:
            if locator.count():
                text = locator.inner_text(timeout=100).strip()
                if text:
                    return text
        except PlaywrightError:
            continue
    return None


def _extract_dom_comments(page, limit=10, warnings=None, expected_count=None, timeout=3000, log_warnings=True):
    """Read only delivered DOM comments; an unavailable list is not proof of zero."""
    limit = max(0, min(limit, 10))
    if not limit:
        return []
    comments = []
    seen = set()
    failures = 0
    logger = logging.getLogger(__name__)

    def warn(message):
        message = f"Comentarios de {urlparse(page.url).path}: {message}"
        if log_warnings:
            logger.warning(message)
        if warnings is not None:
            warnings.append(message)

    try:
        validate_content_page(page)
        try:
            page.locator(", ".join(COMMENT_SELECTORS)).first.wait_for(
                state="attached", timeout=timeout,
            )
        except PlaywrightTimeoutError:
            validate_content_page(page)
            if expected_count == 0:
                logger.debug("Comentarios: contador cero y sin elementos entregados.")
            else:
                warn("TikTok no entregó elementos con los selectores conocidos dentro de 3 s "
                     f"(contador: {expected_count if expected_count is not None else 'desconocido'}). "
                     "No se puede confirmar una lista vacía; faltan comentarios cargados o una estructura DOM verificable.")
            return []

        items = find_comment_items(page)
        if items is None:
            warn("Los elementos desaparecieron antes de poder leerlos; extracción incompleta.")
            return []

        # One browser read avoids per-element auto-waits and excludes nested replies
        # from the author's links and text of their enclosing comment.
        rows = items.evaluate_all("""(items, selectors) => items.slice(0, 60).map(item => {
            const own = el => el.closest(selectors.items) === item;
            const texts = selectors.text.map(selector =>
                [...item.querySelectorAll(selector)].find(own)?.innerText?.trim());
            return {
                visible: !!item.getClientRects().length,
                hrefs: [...item.querySelectorAll('a[href*="/@"]')].filter(own)
                    .slice(0, 10).map(a => a.getAttribute('href')),
                text: texts.find(Boolean) || null
            };
        })""", {"items": ", ".join(COMMENT_SELECTORS), "text": COMMENT_TEXT_SELECTORS})
        for row in rows:
            if not row["visible"]:
                continue
            username = next((name for href in row["hrefs"]
                             if (name := username_from_href(href))), None)
            text = row["text"]
            if not username or not text:
                failures += 1
                continue
            key = (username.casefold(), text)
            if key in seen:
                continue
            seen.add(key)
            comments.append({"username": username, "text": text})
            if len(comments) >= limit:
                break
        if failures:
            warn(f"{failures} elementos sin autor o texto legibles; extracción incompleta.")
        elif not comments:
            warn("Se encontraron contenedores, pero ningún comentario público visible legible; no se confirma una lista vacía.")
    except (PlaywrightError, TikTokPageError) as error:
        reason = str(error) if isinstance(error, TikTokPageError) else "falló la lectura del DOM"
        warn(f"Extracción incompleta: {reason}.")
    return comments


def author_fields(user):
    if not isinstance(user, dict):
        return {}
    return {key: str(value).casefold() if key == "uniqueId" else str(value)
            for key in ("uniqueId", "id", "secUid")
            if isinstance(value := user.get(key), (str, int)) and not isinstance(value, bool) and str(value)}


def users_in(payload):
    module = payload.get("UserModule") if isinstance(payload, dict) else None
    users = module.get("users") if isinstance(module, dict) else None
    return users if isinstance(users, dict) else {}


def profile_author(payloads, username):
    expected = {"uniqueId": username.casefold()}
    for payload in payloads:
        user = payload
        for key in ("__DEFAULT_SCOPE__", "webapp.user-detail", "userInfo", "user"):
            user = user.get(key) if isinstance(user, dict) else None
        identities = [author_fields(user)] + [author_fields(user) for user in users_in(payload).values()
                                            if author_fields(user).get("uniqueId") == username.casefold()]
        for identity in identities:
            if identity and identity.get("uniqueId") != username.casefold():
                return {}
            for key, value in identity.items():
                if key in expected and expected[key] != value:
                    return {}
                expected[key] = value
    return expected


def publication_records(data, publication_id):
    if isinstance(data, dict):
        if str(data.get("id", "")) == str(publication_id) and any(
            key in data for key in ("stats", "author", "authorId", "video", "imagePost")
        ):
            yield data
        for value in data.values():
            yield from publication_records(value, publication_id)
    elif isinstance(data, list):
        for value in data:
            yield from publication_records(value, publication_id)


def publication_evidence(payloads, publication_id, expected_author):
    records = list(publication_records(payloads, publication_id))
    if not records or not expected_author or not expected_author.get("uniqueId"):
        raise TikTokPageError("Autoría no verificable: faltan datos de la publicación o del usuario solicitado.")
    evidence = {}
    for record in records:
        author = record.get("author")
        identities = [author_fields(author)]
        if isinstance(author, str) and author:
            identities = [author_fields(users_in(payload)[author]) for payload in payloads
                          if author in users_in(payload)] or [{"uniqueId": author.casefold()}]
        identities.append(author_fields({"id": record.get("authorId"), "secUid": record.get("authorSecId")}))
        for identity in identities:
            for key, value in identity.items():
                if key in evidence and evidence[key] != value:
                    raise TikTokPageError("Autoría contradictoria: los identificadores de usuario no coinciden.")
                evidence[key] = value
    shared = evidence.keys() & expected_author.keys()
    if any(evidence[key] != expected_author[key] for key in shared):
        raise TikTokPageError("Autoría contradictoria: la publicación pertenece a otra cuenta.")
    if not shared:
        raise TikTokPageError("Autoría no verificable: no hay identificadores de usuario coincidentes.")
    expected = {**expected_author, **evidence}
    dates = set()
    invalid_date = False
    pinned = False
    for record in records:
        if "createTime" in record:
            value = record["createTime"]
            if not isinstance(value, bool) and str(value).isdigit() and 1451606400 <= int(value) <= time() + 300:
                dates.add(int(value))
            else:
                invalid_date = True
        pinned = pinned or record.get("isPinnedItem") is True or record.get("isPinned") is True
    metadata = {"created_at": next(iter(dates)) if len(dates) == 1 and not invalid_date else None,
                "pinned": pinned}
    item = find_video_payload(records, publication_id) or records[0]
    return item, expected, metadata


# Extract video metrics and available public comments.
def extract_video_details(page, video_url, fallback_preview=None, expected_author=None, metadata=None, profile_payloads=(), warnings=None, comment_capture=None):
    validate_content_page(page)
    match = re.fullmatch(r"/@([^/]+)/(video|photo)/(\d+)/?", urlparse(video_url).path)
    if not match:
        raise TikTokPageError("Invalid TikTok video URL.")
    payload = get_embedded_json(page)
    validate_content_page(page)
    item, owner, info = publication_evidence([*payload, *profile_payloads], match.group(3), expected_author)
    if match.group(1).casefold() not in {str(value).casefold() for value in owner.values()}:
        raise TikTokPageError("Autoría contradictoria: el enlace no corresponde al autor confirmado.")
    if metadata is not None:
        metadata.update(info)

    result = {
        "url": video_url,
        "type": match.group(2),
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
        images = (item.get("imagePost") or {}).get("images") or []
        photo_preview = None
        if isinstance(images, list) and images and isinstance(images[0], dict):
            for key in ("imageURL", "displayImage"):
                urls = (images[0].get(key) or {}).get("urlList") or []
                if isinstance(urls, list) and urls and isinstance(urls[0], str):
                    photo_preview = urls[0]
                    break

        result.update(
            {
                "preview_url": (
                        fallback_preview
                        or photo_preview
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
        warnings=warnings,
        capture=comment_capture,
        expected_count=(item.get("stats") or {}).get("commentCount") if item else None,
    )

    return result


# Open each video and read available details.
def extract_latest_videos(context, video_cards, warnings=None, expected_author=None, profile_payloads=()):
    results = []
    metadata_by_id = {}
    candidates = list(video_cards)
    grid_order = {card["id"]: index for index, card in enumerate(candidates)}
    known_dates = {}
    pinned_detected = False
    for card in candidates:
        try:
            _, _, info = publication_evidence(profile_payloads, card["id"], expected_author)
            pinned_detected = pinned_detected or info["pinned"]
            if info["created_at"] is not None:
                known_dates[card["id"]] = info["created_at"]
        except TikTokPageError:
            pass
    ordered = bool(candidates) and len(known_dates) == len(candidates)
    if ordered:
        candidates.sort(key=lambda card: known_dates[card["id"]], reverse=True)
    for number, card in enumerate(candidates, start=1):
        if ordered and len(results) >= 10 and all(metadata_by_id[item["id"]].get("created_at") is not None for item in results):
            break
        video_page = context.new_page()
        comment_capture = CommentResponseCapture(card["id"])
        video_page.on("response", comment_capture.on_response)

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

            validate_content_page(video_page)

            if response and response.status == 200:
                info = {}
                details = extract_video_details(
                    video_page,
                    card["url"],
                    card.get("preview_url"),
                    expected_author=expected_author,
                    metadata=info,
                    profile_payloads=profile_payloads,
                    warnings=warnings,
                    comment_capture=comment_capture,
                )

                result.update(details)
                metadata_by_id[card["id"]] = info

            else:
                raise TikTokPageError(
                    f"Unable to access video (HTTP {response.status if response else 'no response'})."
                )

            results.append(result)
            logging.getLogger(__name__).debug(
                f"Video {number}: "
                f"{len(result['comments_list'])} comments found."
            )

        except (PlaywrightError, TikTokPageError) as error:
            message = str(error) if isinstance(error, TikTokPageError) else "Falló la carga del video en TikTok."
            if warnings is not None:
                warnings.append(f"Publicación {card['id']} descartada: {message}")
            logging.getLogger(__name__).debug(f"Video {number}: {message}")

        finally:
            video_page.remove_listener("response", comment_capture.on_response)
            video_page.close()

    if results and all(metadata_by_id[item["id"]].get("created_at") is not None for item in results):
        results.sort(key=lambda item: metadata_by_id[item["id"]]["created_at"], reverse=True)
    elif results:
        results.sort(key=lambda item: grid_order[item["id"]])
        if warnings is not None:
            warnings.append("Faltan fechas fiables o existen fechas contradictorias; se conserva el orden de la cuadrícula, sin garantizar que sean las diez publicaciones más recientes.")
    if (pinned_detected or any(info.get("pinned") for info in metadata_by_id.values())) and warnings is not None:
        warnings.append("Se detectaron publicaciones fijadas; su posición visual no se utilizó como fecha de publicación.")
    return results[:10]


# Retrieve a public profile and its available details.
def scrape_profile(username):
    username = validate_username(username)
    url = f"https://www.tiktok.com/@{username}"

    with persistent_context(headless=True) as context:
        page = context.new_page()

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        validate_content_page(page)

        if response is None or response.status != 200:
            raise RuntimeError(
                "TikTok no permitió cargar el perfil. Comprueba el username, la conexión y el acceso a la cuenta."
            )

        try:
            page.locator(
                PROFILE_FIELDS["nickname"]
            ).first.wait_for(
                state="visible",
                timeout=15000,
            )

        except PlaywrightTimeoutError:
            validate_content_page(page)
            raise TikTokPageError("No se pudo validar la carga del perfil. Comprueba el acceso desde la configuración de sesión.")

        validate_content_page(page)
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
            logging.getLogger(__name__).debug("Video links unavailable.")

        warnings = []
        try:
            validate_content_page(page)
            payloads = get_embedded_json(page)
            expected_author = profile_author(payloads, username)
            video_cards = get_profile_video_cards(page, limit=None, username=username,
                                                  expected_author=expected_author, warnings=warnings)
        except TikTokPageError as error:
            warnings.append(str(error))
            payloads, expected_author, video_cards = [], {}, []
        profile["videos"] = extract_latest_videos(
            context,
            video_cards,
            warnings=warnings,
            expected_author=expected_author,
            profile_payloads=payloads,
        )
        if len(profile["videos"]) < 10:
            warnings.append(f"Resultado parcial: {len(profile['videos'])} publicaciones verificadas de hasta 10.")
        if any(video["views"] == "N/A" for video in profile["videos"]):
            warnings.append("Algunos videos no tienen estadísticas disponibles; no se sustituyeron con otros videos.")
        if not video_cards:
            warnings.append("No se obtuvieron candidatos de la cuadrícula del perfil; no se utilizaron recomendaciones.")
        profile["_meta"] = {"mode": "real", "warnings": warnings}

        return profile
