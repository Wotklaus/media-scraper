"""Store only dashboard fields from an explicitly authorized real query."""

from datetime import datetime, timezone
import json
import os
import re
from urllib.parse import urlparse

from .scraper import validate_username
from .session import PRIVATE_DIR, private_directory

CAPTURE_DIR = PRIVATE_DIR / "captures"
PROFILE_FIELDS = ("nickname", "followers", "following", "likes", "bio")
VIDEO_FIELDS = ("title", "views", "likes", "comments", "shares", "saves")


class CaptureNotFoundError(RuntimeError):
    pass


def scalar(value):
    if value is not None and not isinstance(value, (str, int, float)):
        raise ValueError("Formato de captura inválido.")
    return value


def dashboard_data(profile):
    username = validate_username(profile["username"])
    result = {key: scalar(profile[key]) for key in PROFILE_FIELDS}
    result.update(username=username, url=f"https://www.tiktok.com/@{username}",
                  avatar_url=None, videos=[])
    for field in ("followers_users", "following_users"):
        result[field] = [validate_username(name) for name in profile[field][:10]]
    for item in profile["videos"][:10]:
        video_id = str(item["id"])
        if not video_id.isdigit():
            raise ValueError("ID de video inválido en la captura.")
        parsed = urlparse(item["url"])
        if (parsed.scheme != "https" or parsed.hostname not in {"www.tiktok.com", "tiktok.com"}
                or not re.fullmatch(r"/@[A-Za-z0-9._]{1,24}/video/" + re.escape(video_id) + r"/?", parsed.path)):
            raise ValueError("URL inválida en la captura.")
        data = {key: scalar(item[key]) for key in VIDEO_FIELDS}
        data.update(id=video_id, url=f"https://www.tiktok.com{parsed.path}",
                    preview_url=None, comments_list=[])
        for comment in item["comments_list"][:10]:
            if not isinstance(comment["text"], str):
                raise ValueError("Comentario inválido en la captura.")
            data["comments_list"].append({
                "username": validate_username(comment["username"]), "text": comment["text"],
            })
        result["videos"].append(data)
    return result


def save_capture(profile):
    if profile.get("_meta", {}).get("mode") != "real":
        raise ValueError("Solo se pueden guardar consultas reales autorizadas.")
    clean = dashboard_data(profile)
    record = {"version": 1, "source": "real", "captured_at": datetime.now(timezone.utc).isoformat(),
              "profile": clean}
    private_directory(CAPTURE_DIR.parent)
    directory = private_directory(CAPTURE_DIR)
    path = directory / f"{clean['username'].lower()}.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError("Ya existe una captura para ese usuario. Renómbrala antes de guardar otra.") from None
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    return path


def load_capture(username):
    username = validate_username(username)
    path = CAPTURE_DIR / f"{username.lower()}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CaptureNotFoundError(
            "No hay una captura guardada para este usuario. Guarda primero una consulta real autorizada."
        ) from None
    except (OSError, ValueError):
        raise RuntimeError("No se pudo leer la captura guardada.") from None
    try:
        if record["version"] != 1 or record["source"] != "real":
            raise ValueError()
        captured_at = record["captured_at"]
        datetime.fromisoformat(captured_at)
        profile = dashboard_data(record["profile"])
        if profile["username"].lower() != username.lower():
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError("La captura guardada tiene un formato inválido.") from None
    profile["_meta"] = {
        "mode": "demo", "captured_at": captured_at,
        "warnings": ["Captura histórica. Las imágenes remotas se omiten para no guardar URLs firmadas."],
    }
    return profile
