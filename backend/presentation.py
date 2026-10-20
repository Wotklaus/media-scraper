"""Print the public result without browser state or URL authentication data."""

import json
from urllib.parse import urlsplit, urlunsplit

PROFILE_FIELDS = ('username', 'nickname', 'bio', 'avatar_url', 'url', 'followers', 'following', 'likes')
VIDEO_FIELDS = ('id', 'url', 'title', 'preview_url', 'views', 'likes', 'comments', 'shares', 'saves')


def public_fields(source, fields):
    result = {}
    for key in fields:
        value = source.get(key)
        if not isinstance(value, (str, int, float, type(None))):
            value = None
        if key in ('url', 'avatar_url', 'preview_url') and isinstance(value, str):
            try:
                parts = urlsplit(value)
                value = urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], parts.path, '', ''))
            except ValueError:
                value = None
        result[key] = value
    return result


def print_profile(profile):
    result = public_fields(profile, PROFILE_FIELDS)
    for key in ('followers_users', 'following_users'):
        if key in profile:
            result[key] = [name for name in profile[key] if isinstance(name, str)]
    result['videos'] = []
    for video in profile.get('videos', []):
        item = public_fields(video, VIDEO_FIELDS)
        if 'comments_list' in video:
            item['comments_list'] = [public_fields(comment, ('username', 'text')) for comment in video['comments_list']]
        result['videos'].append(item)
    if '_meta' in profile:
        meta = profile['_meta']
        result['_meta'] = public_fields(meta, tuple(key for key in ('mode', 'captured_at') if key in meta))
        if 'warnings' in meta:
            result['_meta']['warnings'] = [text for text in meta['warnings'] if isinstance(text, str)]
    print(json.dumps(result, indent=2, ensure_ascii=False))
