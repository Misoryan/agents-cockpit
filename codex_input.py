# -*- coding: utf-8 -*-
"""Codex user input, file mention, and local image helpers."""
import base64
import os
import re
import uuid

import common


MENTION_RE = re.compile(r'(?<!\S)@(?:"([^"]+)"|([^\s@"]+))')
IMAGE_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
IMAGE_DETAIL = {"auto", "low", "high", "original"}
MAX_IMAGES_PER_TURN = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def image_bytes_match_mime(raw, mime):
    raw = raw or b""
    mime = str(mime or "").lower().strip()
    if mime == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if mime in ("image/jpeg", "image/jpg"):
        return raw.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return raw.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


class CodexInputAdapter:
    def __init__(self, session):
        self.session = session

    def path_within_cwd(self, path):
        try:
            cwd = os.path.normcase(os.path.abspath(self.session.cwd))
            candidate = os.path.normcase(os.path.abspath(path))
            return os.path.commonpath([cwd, candidate]) == cwd
        except Exception:
            return False

    def resolve_mention_path(self, raw_path):
        raw_path = str(raw_path or "").strip().strip("\"'")
        if not raw_path:
            return ""
        candidate = raw_path if os.path.isabs(raw_path) else os.path.join(self.session.cwd, raw_path)
        candidate = os.path.abspath(candidate)
        if not self.path_within_cwd(candidate):
            return ""
        if self.session.user and not common.path_allowed_for_user(self.session.user, candidate):
            return ""
        if not os.path.exists(candidate):
            return ""
        return candidate

    def image_upload_dir(self):
        return os.path.join(self.session.state_dir, "codex_uploads", self.session.sid)

    def image_file(self, image_id):
        image_id = os.path.basename(str(image_id or ""))
        if not image_id:
            return ""
        root = os.path.abspath(self.image_upload_dir())
        path = os.path.abspath(os.path.join(root, image_id))
        try:
            if os.path.commonpath([root, path]) != root:
                return ""
        except Exception:
            return ""
        return path if os.path.isfile(path) else ""

    def prepare_image_inputs(self, images):
        if not images:
            return []
        if not isinstance(images, list):
            raise ValueError("images must be an array")
        if len(images) > MAX_IMAGES_PER_TURN:
            raise ValueError("too many images; max %d" % MAX_IMAGES_PER_TURN)
        root = self.image_upload_dir()
        os.makedirs(root, exist_ok=True)
        out = []
        for idx, image in enumerate(images):
            if not isinstance(image, dict):
                raise ValueError("image %d is invalid" % (idx + 1))
            data_url = str(image.get("data_url") or image.get("dataUrl") or "")
            raw_b64 = str(image.get("data") or "")
            mime = str(image.get("mime") or image.get("type") or "").split(";", 1)[0].lower().strip()
            if data_url.startswith("data:"):
                header, sep, payload = data_url.partition(",")
                if not sep or ";base64" not in header:
                    raise ValueError("image %d must be base64 data URL" % (idx + 1))
                mime = header[5:].split(";", 1)[0].lower().strip()
                raw_b64 = payload
            if mime not in IMAGE_MIME_EXT:
                raise ValueError("unsupported image type: %s" % (mime or "unknown"))
            try:
                raw = base64.b64decode(raw_b64, validate=True)
            except Exception:
                raise ValueError("image %d has invalid base64 data" % (idx + 1))
            if not raw:
                raise ValueError("image %d is empty" % (idx + 1))
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("image %d exceeds %d MB" % (idx + 1, MAX_IMAGE_BYTES // (1024 * 1024)))
            if not image_bytes_match_mime(raw, mime):
                raise ValueError("image %d does not match declared type" % (idx + 1))
            image_id = uuid.uuid4().hex + IMAGE_MIME_EXT[mime]
            path = os.path.join(root, image_id)
            with open(path, "wb") as handle:
                handle.write(raw)
            detail = str(image.get("detail") or "auto").strip().lower()
            if detail not in IMAGE_DETAIL:
                detail = "auto"
            out.append({
                "type": "localImage",
                "path": os.path.abspath(path),
                "name": str(image.get("name") or image_id),
                "image_id": image_id,
                "mime": mime,
                "size": len(raw),
                "detail": detail,
            })
        return out

    def display_user_content(self, text, image_inputs=None):
        blocks = []
        if str(text or "").strip():
            blocks.append({"type": "text", "text": str(text or "")})
        for image in image_inputs or []:
            if not isinstance(image, dict):
                continue
            blocks.append({
                "type": "localImage",
                "path": image.get("path") or "",
                "name": image.get("name") or os.path.basename(image.get("path") or ""),
                "image_id": image.get("image_id") or "",
                "mime": image.get("mime") or "",
                "size": image.get("size") or 0,
            })
        return blocks if blocks else str(text or "")

    def user_input_items(self, text, image_inputs=None):
        text = str(text or "")
        items = []
        if text.strip() or not image_inputs:
            items.append({"type": "text", "text": text, "text_elements": []})
        seen = set()
        for match in MENTION_RE.finditer(text):
            raw_path = match.group(1) or match.group(2) or ""
            path = self.resolve_mention_path(raw_path)
            if not path or path in seen:
                continue
            seen.add(path)
            items.append({
                "type": "mention",
                "path": path,
                "name": os.path.basename(path) or path,
            })
        for image in image_inputs or []:
            if not isinstance(image, dict):
                continue
            path = image.get("path") or ""
            if not path:
                continue
            item = {"type": "localImage", "path": path}
            detail = image.get("detail")
            if detail in IMAGE_DETAIL:
                item["detail"] = detail
            items.append(item)
        return items

    def search_file_result(self, item):
        if not isinstance(item, dict):
            return None
        root = item.get("root") or self.session.cwd
        path = item.get("path") or ""
        if not path:
            return None
        abs_path = path if os.path.isabs(path) else os.path.abspath(os.path.join(root, path))
        if not self.path_within_cwd(abs_path):
            return None
        rel = os.path.relpath(abs_path, self.session.cwd)
        if rel == ".":
            rel = os.path.basename(abs_path)
        rel = rel.replace(os.sep, "/")
        return {
            "path": abs_path,
            "insert": rel,
            "name": item.get("file_name") or os.path.basename(abs_path) or rel,
            "match_type": item.get("match_type") or ("directory" if os.path.isdir(abs_path) else "file"),
            "score": item.get("score") or 0,
        }

    def search_files(self, query, limit=20):
        query = str(query or "").strip()
        if not query:
            return {"ok": True, "files": []}
        try:
            limit = max(1, min(50, int(limit or 20)))
        except Exception:
            limit = 20
        self.session._client().ensure()
        res = self.session._client().request(
            "fuzzyFileSearch",
            {"query": query, "roots": [self.session.cwd]},
            timeout=15,
        ) or {}
        files = []
        for item in (res.get("files") or []):
            result = self.search_file_result(item)
            if result:
                files.append(result)
            if len(files) >= limit:
                break
        return {"ok": True, "files": files}
