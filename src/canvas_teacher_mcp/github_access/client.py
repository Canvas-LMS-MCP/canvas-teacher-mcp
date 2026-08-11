"""github_access.client — GitHub REST transport (login-free).

Pure HTTP over the GitHub REST API: paginated GET (+ raw bytes for log zips).
Every function takes (token, ...) — it never acquires a token (login lives in
github_auth) and hardcodes nothing course/grading-specific. The generic GitHub
client, mirroring canvas_rest.client on the GitHub side.
"""
import json
import re
import time
import urllib.error
import urllib.request


def _http(url, headers, raw=False, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                link = r.headers.get("Link", "") or ""
                if raw:
                    return body, link
                return json.loads(body), link
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, ""
            if e.code in (502, 503, 429):
                time.sleep(2 * (attempt + 1))
                continue
            return None, ""
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None, ""


def get(token, path, paginate=True):
    """Paginated GET. `path` may be a relative API path or a full URL."""
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    if "?" not in url:
        url += "?per_page=100"
    elif "per_page" not in url:
        url += "&per_page=100"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    items = []
    while url:
        data, link = _http(url, headers)
        if data is None:
            return None
        if isinstance(data, list):
            items.extend(data)
        else:
            return data
        if not paginate:
            break
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return items
