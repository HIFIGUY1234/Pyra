"""Provider-neutral object storage for large artefacts (archives, granules, rasters, Parquet, models, reports).

    PYROSCOPE_STORAGE=local      (default) files under data/object_store/<bucket>/<key>
    PYROSCOPE_STORAGE=supabase   Supabase Storage REST API; needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (backend only)

Both backends implement upload / download / delete / metadata / signed_url with SHA-256 recorded in the
`storage_objects` table. Supabase uploads above RESUMABLE_MIN use the TUS resumable endpoint (6 MiB chunks,
resumes from the server's offset after a failure). Transient HTTP errors (429/5xx/network) are retried with
exponential backoff. Buckets are private; browsers only ever receive time-limited signed URLs.
Large binaries are never stored in PostgreSQL.
"""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from .config import DATA

BUCKETS = ("raw-satellite-archives", "viirs750-granules", "geostationary-data", "processed-parquet", "burned-area-data",
           "emissions-data", "smoke-outputs", "geo-data", "population-data", "model-artifacts", "scientific-reports", "user-uploads")
CHUNK = 6 * 1024 * 1024
RESUMABLE_MIN = 6 * 1024 * 1024


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _check_key(bucket: str, key: str):
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket}; allowed {list(BUCKETS)}")
    if not key or key.startswith("/") or "\\" in key or any(part in ("", ".", "..") for part in key.split("/")):
        raise ValueError("object key must be a relative path without '.', '..' or empty segments")


class LocalStorage:
    name = "local"

    def __init__(self, root: Path | None = None):
        self.root = Path(root or os.getenv("PYROSCOPE_OBJECT_STORE", DATA / "object_store"))

    def _path(self, bucket, key) -> Path:
        _check_key(bucket, key)
        p = (self.root / bucket / key).resolve()
        if (self.root / bucket).resolve() not in p.parents:
            raise ValueError("key escapes bucket")
        return p

    def upload(self, bucket: str, key: str, src: Path, content_type: str = "application/octet-stream") -> dict:
        p = self._path(bucket, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        shutil.copyfile(src, tmp)
        tmp.replace(p)
        return {"bucket": bucket, "key": key, "bytes": p.stat().st_size, "sha256": sha256_file(p), "backend": self.name}

    def download(self, bucket: str, key: str, dest: Path) -> Path:
        p = self._path(bucket, key)
        if not p.exists():
            raise KeyError(f"{bucket}/{key} not found")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        return dest

    def delete(self, bucket: str, key: str) -> bool:
        p = self._path(bucket, key)
        if p.exists():
            p.unlink()
            return True
        return False

    def metadata(self, bucket: str, key: str) -> dict:
        p = self._path(bucket, key)
        if not p.exists():
            raise KeyError(f"{bucket}/{key} not found")
        return {"bucket": bucket, "key": key, "bytes": p.stat().st_size, "sha256": sha256_file(p), "backend": self.name}

    def signed_url(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        self.metadata(bucket, key)
        return f"/api/storage/local/{bucket}/{quote(key)}"       # served by the API with the caller's authorisation


class SupabaseStorage:
    name = "supabase"

    def __init__(self, url: str | None = None, key: str | None = None, session=None, retries: int = 4, sleep=time.sleep):
        import requests
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not self.url or not self.key:
            raise PermissionError("BLOCKED_BY_CREDENTIALS: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        if not self.url.startswith("https://") and not self.url.startswith("http://127.0.0.1") and not self.url.startswith("http://localhost"):
            raise ValueError("SUPABASE_URL must be https")
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {self.key}", "apikey": self.key})
        self.retries, self.sleep = retries, sleep

    def _req(self, method: str, path: str, **kw):
        last = None
        for a in range(self.retries):
            try:
                r = self.s.request(method, f"{self.url}/storage/v1/{path}", timeout=kw.pop("timeout", 300), **kw)
            except Exception as exc:          # network error: retry
                last = exc
            else:
                if r.status_code in (429, 500, 502, 503, 504):
                    last = RuntimeError(f"HTTP {r.status_code}")
                else:
                    if r.status_code in (401, 403):
                        raise PermissionError(f"Supabase Storage refused the request (HTTP {r.status_code})")
                    if r.status_code == 404 or (r.status_code == 400 and "not found" in r.text.lower()):
                        raise KeyError(path)
                    if r.status_code >= 400:
                        raise RuntimeError(f"Supabase Storage HTTP {r.status_code}: {r.text[:200]}")
                    return r
            self.sleep(2 ** a)
        raise RuntimeError(f"Supabase Storage unavailable after {self.retries} attempts: {last}")

    def ensure_buckets(self, file_size_limit: int | None = None) -> list[str]:
        have = {b["id"] for b in self._req("GET", "bucket").json()}
        made = []
        for b in BUCKETS:
            if b not in have:
                body = {"id": b, "name": b, "public": False}
                if file_size_limit:
                    body["file_size_limit"] = file_size_limit
                self._req("POST", "bucket", json=body)
                made.append(b)
        return made

    def upload(self, bucket: str, key: str, src: Path, content_type: str = "application/octet-stream") -> dict:
        _check_key(bucket, key)
        size = src.stat().st_size
        if size >= RESUMABLE_MIN:
            self._tus_upload(bucket, key, src, content_type)
        else:
            with open(src, "rb") as f:
                self._req("POST", f"object/{bucket}/{quote(key)}", data=f.read(), headers={"Content-Type": content_type, "x-upsert": "true"})
        return {"bucket": bucket, "key": key, "bytes": size, "sha256": sha256_file(src), "backend": self.name}

    def _tus_upload(self, bucket: str, key: str, src: Path, content_type: str):
        b64 = lambda x: base64.b64encode(x.encode()).decode()
        size = src.stat().st_size
        r = self._req("POST", "upload/resumable", headers={
            "Tus-Resumable": "1.0.0", "Upload-Length": str(size), "x-upsert": "true",
            "Upload-Metadata": f"bucketName {b64(bucket)},objectName {b64(key)},contentType {b64(content_type)}"})
        loc = r.headers["Location"]
        rel = loc.split("/storage/v1/", 1)[1] if "/storage/v1/" in loc else loc
        offset, resumes = 0, 0
        with open(src, "rb") as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(CHUNK)
                try:
                    r = self._req("PATCH", rel, data=chunk, headers={"Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                                                                    "Content-Type": "application/offset+octet-stream"})
                    offset = int(r.headers.get("Upload-Offset", offset + len(chunk)))
                except RuntimeError:
                    resumes += 1
                    if resumes > 5:
                        raise
                    # resume from what the server actually has
                    h = self._req("HEAD", rel, headers={"Tus-Resumable": "1.0.0"})
                    offset = int(h.headers["Upload-Offset"])

    def download(self, bucket: str, key: str, dest: Path) -> Path:
        _check_key(bucket, key)
        r = self._req("GET", f"object/authenticated/{bucket}/{quote(key)}", stream=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for c in r.iter_content(1 << 20):
                f.write(c)
        tmp.replace(dest)
        return dest

    def delete(self, bucket: str, key: str) -> bool:
        _check_key(bucket, key)
        r = self._req("DELETE", f"object/{bucket}", json={"prefixes": [key]})
        return bool(r.json())

    def metadata(self, bucket: str, key: str) -> dict:
        _check_key(bucket, key)
        r = self._req("GET", f"object/info/authenticated/{bucket}/{quote(key)}")
        d = r.json()
        return {"bucket": bucket, "key": key, "bytes": d.get("size") or (d.get("metadata") or {}).get("size"), "backend": self.name, "raw": d}

    def signed_url(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        _check_key(bucket, key)
        if not 60 <= expires_s <= 7 * 86400:
            raise ValueError("expires_s must be 60 s - 7 days")
        r = self._req("POST", f"object/sign/{bucket}/{quote(key)}", json={"expiresIn": expires_s})
        return f"{self.url}/storage/v1{r.json()['signedURL']}"


def get_storage():
    kind = os.getenv("PYROSCOPE_STORAGE", "local").lower()
    if kind == "local":
        return LocalStorage()
    if kind == "supabase":
        return SupabaseStorage()
    raise ValueError("PYROSCOPE_STORAGE must be local or supabase")


def put(bucket: str, key: str, src: Path, actor: str = "system", content_type: str = "application/octet-stream", meta: dict | None = None) -> dict:
    """Upload and register (bucket, key, sha256, bytes) in storage_objects."""
    from sqlalchemy import select
    from . import models as M
    res = get_storage().upload(bucket, key, Path(src), content_type)
    with M.Session() as s:
        o = s.scalar(select(M.StorageObject).where(M.StorageObject.bucket == bucket, M.StorageObject.key == key))
        if o is None:
            o = M.StorageObject(bucket=bucket, key=key)
            s.add(o)
        o.sha256, o.bytes, o.content_type, o.backend, o.meta, o.created_by = res["sha256"], res["bytes"], content_type, res["backend"], meta, actor
        s.commit()
    return res


def status() -> dict:
    kind = os.getenv("PYROSCOPE_STORAGE", "local").lower()
    out = {"backend": kind, "buckets": list(BUCKETS)}
    if kind == "supabase":
        out["configured"] = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        out["note"] = "Free plan: 50 MB per file; Pro and above: configurable global limit (up to 500 GB). Large FIRMS archives need a paid plan or stay in Git LFS."
    else:
        out["configured"] = True
        out["root"] = "data/object_store"
    return out
