"""canvas_rest.files — upload a local file into a Canvas course's Files (3-step API).

Canvas file upload is 3 steps:
  1. notify Canvas: POST /courses/{cid}/files (name, size, content_type, folder) -> {upload_url, upload_params}
  2. POST the file as multipart/form-data to that upload_url (the upload_params carry the auth,
     NOT the Bearer token); the file field goes LAST.
  3. the response IS the created file object (inst-fs returns it directly, or via a redirect that
     urllib follows automatically).

Used to bring an image into a course before embedding it in a page/assignment — a cross-course file
URL (`/courses/<other>/files/...`) won't render, so re-host the file in THIS course first.
"""
import json
import mimetypes
import os
import urllib.request

from .client import post

_BOUNDARY = "----canvasRestMultipartBoundary7MA4YWxkTrZu0gW"


def _multipart(params, file_field, filename, content_type, file_bytes):
    """Build a multipart/form-data body: all params first, the file field last."""
    out = []
    for k, v in params.items():
        out.append("--" + _BOUNDARY)
        out.append('Content-Disposition: form-data; name="%s"' % k)
        out.append("")
        out.append(str(v))
    out.append("--" + _BOUNDARY)
    out.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (file_field, filename))
    out.append("Content-Type: %s" % content_type)
    out.append("")
    head = ("\r\n".join(out) + "\r\n").encode("utf-8")
    tail = ("\r\n--" + _BOUNDARY + "--\r\n").encode("utf-8")
    return head + file_bytes + tail


def upload_file(base_url, token, course_id, file_path, name=None,
                parent_folder_path="uploaded", content_type=None):
    """Upload a local file to a course's Files. Returns the created file dict
    (has `id`, `display_name`, `url`). Embed an image with
    `https://<host>/courses/<cid>/files/<id>/preview`.
    """
    name = name or os.path.basename(file_path)
    content_type = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    size = os.path.getsize(file_path)

    # 1. notify Canvas
    status, info = post(base_url, token, f"/courses/{course_id}/files",
                        {"name": name, "size": size, "content_type": content_type,
                         "parent_folder_path": parent_folder_path, "on_duplicate": "rename"})
    if not isinstance(info, dict) or "upload_url" not in info:
        raise RuntimeError(f"upload step 1 failed (HTTP {status}): {info}")

    # 2. multipart POST the bytes to the returned upload_url (params carry auth, no Bearer)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    body = _multipart(info.get("upload_params") or {}, "file", name, content_type, file_bytes)
    req = urllib.request.Request(
        info["upload_url"], data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + _BOUNDARY},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()

    # 3. response is the created file object (direct, or via a followed redirect)
    try:
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"upload step 2/3 returned non-JSON: {raw[:300]!r}") from e
