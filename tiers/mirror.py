"""Reading the bucket, and mirroring every image into local state.

Two rules from doc/cards.md:

  the browser never requests a third party, whatever the input said
  a key that resolves to nothing is loud, never a broken image tag
"""

import configparser
import hashlib
import ipaddress
import re
import json
import os
import pathlib
import socket
import urllib.error
import urllib.parse
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


class BlockedAddress(Exception):
    """A url resolved somewhere this process must never fetch.

    spain is the house router. Loopback there holds Garage on 3900, Authelia
    on 9091 and lldap on 17170, so a fetch of an attacker-named url is an SSRF
    with the whole estate behind it.
    """


class CredentialError(Exception):
    """The credential file is absent, empty or malformed.

    Separate from MissingObject because the two mean opposite things: one is
    bad input, the other is a broken deployment.
    """


def _credential_path():
    """The secret arrives as a FILE. Never an argument, never an environment value."""
    d = os.environ.get("CREDENTIALS_DIRECTORY")
    if d:
        return os.path.join(d, "garage")
    return os.environ.get("TIERS_CREDENTIALS_FILE") or os.path.expanduser(
        "~/.config/gluck-tiers/credentials"
    )


def client():
    """Build an S3 client from the credential FILE, and from nothing else.

    boto3 will search the environment, ~/.aws and instance metadata before
    admitting defeat, so a working read is not evidence that it used the
    credential you meant. Keys are therefore passed explicitly and every
    failure to read the file is loud. tests/test_credential.py proves that in
    a clean room.
    """
    path = _credential_path()
    if not os.path.exists(path):
        raise CredentialError(f"no garage credential file at {path}")
    if os.path.getsize(path) == 0:
        raise CredentialError(f"garage credential file is empty: {path}")
    cp = configparser.ConfigParser()
    try:
        cp.read(path)
    except configparser.Error as e:
        raise CredentialError(f"credential file is not an ini file: {path}: {e}") from e
    if not cp.sections():
        raise CredentialError(f"credential file holds no profile section: {path}")
    section = "tiers-ro" if cp.has_section("tiers-ro") else cp.sections()[0]
    for field in ("aws_access_key_id", "aws_secret_access_key"):
        if not cp.has_option(section, field) or not cp.get(section, field).strip():
            raise CredentialError(f"profile [{section}] has no {field}: {path}")
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


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is a second url, and the second one was never checked.

    Validating the first host and then following a 302 to 127.0.0.1 is the
    classic way an SSRF guard is defeated, so redirects are refused outright.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BlockedAddress(f"redirect refused: {req.full_url} -> {newurl}")


_OPENER = urllib.request.build_opener(_NoRedirects)


def assert_fetchable(url):
    """Refuse anything that is not public http(s). Raises BlockedAddress."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedAddress(f"scheme not allowed: {parts.scheme or 'none'}")
    host = parts.hostname
    if not host:
        raise BlockedAddress(f"no host in url: {url!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as e:
        raise BlockedAddress(f"{host} does not resolve: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise BlockedAddress(f"{host} resolves to {ip}, which is not public")
    return True


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

    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    SHA_RE = re.compile(r"^(?:/img/)?([0-9a-f]{64})$")

    def already_mirrored(self, source):
        """Resolve ONLY to bytes this service has already mirrored.

        The whole import security boundary is this method. An imported list may
        reuse a cover that an admin-controlled input already brought in, and can
        reach nothing else: no bucket key, no url, no fetch. doc/imports.md.
        """
        m = self.SHA_RE.match((source or "").strip())
        if not m:
            raise MissingObject(
                f"an imported list may only name an already-mirrored image, "
                f"not {source!r}"
            )
        sha = m.group(1)
        if not self.path_for(sha):
            raise MissingObject(f"{sha} is not in the mirror")
        return sha

    def ingest(self, source, s3=None, timeout=15, *, allow_remote, allow_keys):
        """Return the sha256 for one image source, fetching it at most once.

        allow_remote is the PROVENANCE of the input, not a property of the
        url. A bucket object is admin-controlled, so a remote fetch is
        intended: it is how the browser never touches Spotify's CDN. An
        IMPORTED file is user-supplied, so no fetch may happen at all, and an
        image resolves only if its bytes are already mirrored. doc/imports.md.
        """
        if not source:
            return None
        # Neither flag is defaulted, so no call site can inherit permission
        # it never asked for. A default is a decision nobody re-reads.
        if not allow_remote and not allow_keys:
            return self.already_mirrored(source)

        if source in self.index:
            sha = self.index[source]
            if self.path_for(sha):
                return sha

        if source.startswith(("http://", "https://")):
            if not allow_remote:
                raise MissingObject(
                    f"remote images are not fetched for imported lists: {source}"
                )
            assert_fetchable(source)
            req = urllib.request.Request(source, headers={"User-Agent": "gluck-tiers"})
            try:
                with _OPENER.open(req, timeout=timeout) as r:
                    blob = r.read(self.MAX_IMAGE_BYTES + 1)
            except BlockedAddress:
                raise
            except Exception as e:
                raise MissingObject(f"{source} could not be fetched: {e}") from e
            if len(blob) > self.MAX_IMAGE_BYTES:
                raise MissingObject(
                    f"{source} exceeds {self.MAX_IMAGE_BYTES} bytes, refused"
                )
        else:
            if not allow_keys:
                raise MissingObject(
                    f"this input may not name a bucket key: {source!r}"
                )
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

    def ingest_list(self, items, s3=None, *, allow_remote, allow_keys):
        """Mirror every image in a parsed list.

        Returns (items, errors). An item whose image cannot be resolved gets
        img None so it renders as a text chip, and the failure is returned
        rather than swallowed: the caller logs it and the status endpoint
        counts it. Silence is the one outcome that is forbidden.
        """
        # An import needs no S3 client at all, which is itself a property:
        # the credential is never even constructed on that path.
        s3 = s3 if s3 is not None else (client() if allow_keys else None)
        errors = []
        out = []
        for item in items:
            card = dict(item)
            source = card.get("img") or card.get("img_url")
            card["img"] = None
            if source:
                try:
                    sha = self.ingest(
                        source, s3=s3, allow_remote=allow_remote, allow_keys=allow_keys
                    )
                    card["img"] = f"/img/{sha}" if sha else None
                except (MissingObject, BlockedAddress) as e:
                    errors.append({"id": card.get("id"), "source": source, "error": str(e)})
            out.append(card)
        return out, errors
