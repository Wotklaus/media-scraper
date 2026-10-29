"""Pure normalization of scraper results; no database connection or writes."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re


_COUNTER = re.compile(r"(\d+(?:\.\d+)?)\s*([KMB])?")
_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _counter_value(value):
    """Return None for unavailable counters; abbreviated counts are approximate."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        match = _COUNTER.fullmatch(value.strip().upper().replace(",", "."))
        if not match:
            return None
        number, suffix = match.groups()
    else:
        number, suffix = str(value), None
    try:
        number = Decimal(number)
        if not number.is_finite() or number < 0:
            return None
        return int(number * _MULTIPLIERS.get(suffix, 1))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def normalize_number(value):
    """Convert counters such as 18.6K to integers; return 0 for invalid values."""
    number = _counter_value(value)
    return number if number is not None else 0


def _tiktok_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("TikTok IDs must be nonempty strings or integers.")
    return str(value)


def normalize_profile(profile):
    """Return profile, publications, comments and extraction_metadata documents.

    metrics.comments_count is TikTok's reported counter, potentially rounded.
    retrieved_comments_count counts delivered individual records only. Neither
    an empty list nor a matching counter establishes extraction completeness.
    Unknown metrics and completeness are represented by None, never inferred.
    Input data is not mutated. Only explicitly supported public fields are copied.
    """
    if not isinstance(profile, dict):
        raise ValueError("The scraped profile must be an object.")
    username = profile.get("username")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("The scraped profile requires a username.")

    normalized_profile = {
        "username": username,
        "nickname": profile.get("nickname"),
        "bio": profile.get("bio"),
        "avatar_url": profile.get("avatar_url"),
        "url": profile.get("url"),
        "metrics": {key: _counter_value(profile.get(key))
                    for key in ("followers", "following", "likes")},
    }
    for key in ("id", "secUid"):
        if profile.get(key) is not None:
            normalized_profile[key] = _tiktok_id(profile[key])
    for key in ("followers_users", "following_users"):
        if key in profile:
            normalized_profile[key] = deepcopy(profile[key])

    publications, comments = [], []
    videos = profile.get("videos")
    if videos is None:
        videos = []
    if not isinstance(videos, list):
        raise ValueError("Publications must be a list.")
    for video in videos:
        if not isinstance(video, dict):
            raise ValueError("Each publication must be an object.")
        video_id = _tiktok_id(video.get("id"))
        comment_list = video.get("comments_list")
        if comment_list is None:
            comment_list = []
        if not isinstance(comment_list, list):
            raise ValueError("Individual comments must be a list.")
        publication = {
            "publication_id": video_id,
            "profile_username": username,
            "url": video.get("url"),
            "type": video.get("type"),
            "description": video.get("title"),
            "preview_url": video.get("preview_url"),
            "metrics": {
                "views": _counter_value(video.get("views")),
                "likes": _counter_value(video.get("likes")),
                "comments_count": _counter_value(video.get("comments")),
                "shares": _counter_value(video.get("shares")),
                "saves": _counter_value(video.get("saves")),
            },
            "retrieved_comments_count": len(comment_list),
            "comments_status": "recovered" if comment_list else "not_recovered",
            "comments_complete": None,
        }
        # Optional verified source metadata from the integrated original engine.
        for key in ('created_at', 'author'):
            if key in video:
                publication[key] = deepcopy(video[key])
        publications.append(publication)
        for comment in comment_list:
            if (not isinstance(comment, dict)
                    or not isinstance(comment.get("username"), str) or not comment["username"].strip()
                    or not isinstance(comment.get("text"), str) or not comment["text"].strip()):
                raise ValueError("Each recovered comment requires a username and text.")
            document = {
                "publication_id": video_id,
                "profile_username": username,
                "comment_id": _tiktok_id(comment["cid"]) if comment.get("cid") is not None else None,
                "username": comment["username"],
                "text": comment["text"],
            }
            for key in ("create_time", "digg_count", "reply_comment_total"):
                if key in comment:
                    document[key] = _counter_value(comment[key])
            if "comment_language" in comment:
                document["comment_language"] = comment["comment_language"]
            comments.append(document)

    meta = profile.get("_meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("Extraction metadata must be an object.")
    extraction_metadata = {
        "profile_username": username,
        "normalized_at": datetime.now(timezone.utc).isoformat(),
        "mode": meta.get("mode"),
        "warnings": deepcopy(meta.get("warnings", [])),
        "publications_count": len(publications),
        "retrieved_comments_count": len(comments),
        "publications_with_retrieved_comments": sum(bool(item["retrieved_comments_count"]) for item in publications),
    }
    for key in ('engine', 'upstream_commit'):
        if key in meta:
            extraction_metadata[key] = meta[key]
    if "captured_at" in meta:
        extraction_metadata["captured_at"] = meta["captured_at"]
    return {
        "profile": normalized_profile,
        "publications": publications,
        "comments": comments,
        "extraction_metadata": extraction_metadata,
    }
