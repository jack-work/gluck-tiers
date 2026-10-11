"""Reading the bucket, and mirroring every image into local state.

Two rules from doc/cards.md:

  the browser never requests a third party, whatever the input said
  a key that resolves to nothing is loud, never a broken image tag
"""

import configparser
import hashlib
import json
import os
import pathlib
import urllib.request

import boto3
from botocore.config import Config

BUCKET = os.environ.get("TIERS_BUCKET", "files")
PREFIX = os.environ.get("TIERS_PREFIX", "tiers/")
ENDPOINT = os.environ.get("TIERS_S3_ENDPOINT", "http://127.0.0.1:3900")
REGION = os.environ.get("TIERS_S3_REGION", "spain")
EXT_BY_MAGIC = [
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"RIFF", ".webp"),
    (b"GIF8", ".gif"),
]


class MissingObject(Exception):
    """A key or URL named by the input resolved to nothing."""


def _credential_path():
    """The secret arrives as a FILE. Never an argument, never an environment value."""
    d = os.environ.get("CREDENTIALS_DIRECTORY")
    if d:
        return os.path.join(d, "garage")
    return os.environ.get("TIERS_CREDENTIALS_FILE") or os.path.expanduser(
        "~/.config/gluck-tiers/credentials"
    )


def client():
    path = _credential_path()
    if not os.path.exists(path):
        raise RuntimeError(f"no garage credential at {path}")
    cp = configparser.ConfigParser()
    cp.read(path)
    section = "tiers-ro" if cp.has_section("tiers-ro") else cp.sections()[0]
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id=cp.get(section, "aws_access_key_id"),
        aws_secret_access_key=cp.get(section, "aws_secret_access_key"),
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def list_inputs(s3=None):
    """Input files under the prefix, images excluded."""
    s3 = s3 or client()
    out = []
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": PREFIX, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith((".json", ".txt", ".csv")):
                out.append({"key": key, "size": obj["Size"]})
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")


def get_object(key, s3=None):
    s3 = s3 or client()
    try:
        return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey as e:
        raise MissingObject(f"{BUCKET}/{key} does not exist") from e
    except Exception as e:  # botocore raises ClientError for 404 on some paths
        if "NoSuchKey" in repr(e) or "404" in repr(e):
            raise MissingObject(f"{BUCKET}/{key} does not exist") from e
        raise


def _ext(blob):
    for magic, ext in EXT_BY_MAGIC:
        if blob.startswith(magic):
            return ext
    return ".bin"


class Mirror:
    """Content-addressed image store on local disk.

    Local disk rather than Garage because the mirror is derived data: it can
    always be rebuilt from the input file, and Garage has no versioning to
    protect it anyway. The service's key is read-only for the same reason.
    """

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.dir = self.root / "img"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "mirror-index.json"
        self.index = {}
        if self.index_path.exists():
            try:
                self.index = json.loads(self.index_path.read_text())
            except json.JSONDecodeError:
                self.index = {}

    def _save_index(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, indent=1, sort_keys=True))
        tmp.replace(self.index_path)

    def path_for(self, sha):
        for p in self.dir.glob(sha + ".*"):
            return p
        return None

    def ingest(self, source, s3=None, timeout=15):
        """Return the sha256 for one image source, fetching it at most once.

        source is a bucket key or an http(s) URL. Dedup is on the source first,
        then on the bytes, because 72 tracks share 61 covers.
        """
        if not source:
            return None
        if source in self.index:
            sha = self.index[source]
            if self.path_for(sha):
                return sha

        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": "gluck-tiers"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    blob = r.read()
            except Exception as e:
                raise MissingObject(f"{source} could not be fetched: {e}") from e
        else:
            blob = get_object(source, s3=s3)

        if not blob:
            raise MissingObject(f"{source} returned no bytes")

        sha = hashlib.sha256(blob).hexdigest()
        if not self.path_for(sha):
            target = self.dir / (sha + _ext(blob))
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(blob)
            tmp.replace(target)
        self.index[source] = sha
        self._save_index()
        return sha

    def ingest_list(self, items, s3=None):
        """Mirror every image in a parsed list.

        Returns (items, errors). An item whose image cannot be resolved gets
        img None so it renders as a text chip, and the failure is returned
        rather than swallowed: the caller logs it and the status endpoint
        counts it. Silence is the one outcome that is forbidden.
        """
        s3 = s3 or client()
        errors = []
        out = []
        for item in items:
            card = dict(item)
            source = card.get("img") or card.get("img_url")
            card["img"] = None
            if source:
                try:
                    sha = self.ingest(source, s3=s3)
                    card["img"] = f"/img/{sha}" if sha else None
                except MissingObject as e:
                    errors.append({"id": card.get("id"), "source": source, "error": str(e)})
            out.append(card)
        return out, errors
