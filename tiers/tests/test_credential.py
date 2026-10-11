"""Clean-room credential control.

The AWS SDK searches the ambient environment, then ~/.aws, then instance
metadata before admitting defeat, so a successful S3 read is NOT evidence that
the code used the credential you meant. The coordinator e2409a50 was fooled by
this shape tonight: a sops control with its key pointed at /dev/null still
decrypted, because sops found a key by other means.

So every case below runs in a subprocess with a scrubbed environment and HOME
pointed at an empty directory, exactly like `env -i HOME=/empty`.

Case 6 is the one that makes the other five mean anything: the REAL credential
in the SAME clean room must succeed. A clean room that fails everything proves
nothing about credentials.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TIERS = os.path.join(HERE, "..")
ENDPOINT = os.environ.get("TIERS_S3_ENDPOINT", "http://127.0.0.1:3900")
REAL = os.environ.get("TIERS_CREDENTIALS_FILE") or os.path.expanduser(
    "~/.config/gluck-tiers/credentials"
)

PROBE = """
import sys
sys.path.insert(0, %r)
import mirror
try:
    keys = mirror.list_inputs()
except mirror.CredentialError as e:
    print("CREDENTIAL_ERROR: %%s" %% e)
    raise SystemExit(10)
except Exception as e:
    print("S3_REFUSED: %%s: %%s" %% (type(e).__name__, str(e)[:160]))
    raise SystemExit(11)
print("READ_OK: %%d input file(s)" %% len(keys))
""" % TIERS

empty_home = tempfile.mkdtemp(prefix="tiers-clean-home-")
tmp = tempfile.mkdtemp(prefix="tiers-clean-")


def clean_run(cred_path):
    """env -i, with HOME somewhere empty. No AWS_* anything."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": empty_home,
        "TIERS_S3_ENDPOINT": ENDPOINT,
        "TIERS_CREDENTIALS_FILE": cred_path,
    }
    leaked = [k for k in env if k.startswith("AWS_")]
    assert not leaked, f"clean room is not clean: {leaked}"
    p = subprocess.run(
        [sys.executable, "-c", PROBE], env=env, capture_output=True, text=True
    )
    # The WHOLE output, because configparser raises a multi-line error and a
    # last-line assertion silently misses the sentence that matters. That bug
    # was in this file first.
    out = (p.stdout + p.stderr).strip()
    first = next((l for l in out.splitlines() if "CREDENTIAL_ERROR" in l or "S3_REFUSED" in l or "READ_OK" in l), out.splitlines()[-1] if out else "")
    return p.returncode, first, out


def write(name, text):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(text)
    return path


cases = [
    ("absent file", os.path.join(tmp, "does-not-exist"), 10, "no garage credential file at"),
    ("truncated to zero bytes", write("empty", ""), 10, "is empty"),
    ("not an ini file at all", write("junk", "this is not ini\n"), 10, "not an ini file"),
    (
        "profile with a blank secret",
        write("blank", "[tiers-ro]\naws_access_key_id = GKdeadbeef\naws_secret_access_key =\n"),
        10,
        "has no aws_secret_access_key",
    ),
    (
        "well-formed but WRONG keys",
        write(
            "wrong",
            "[tiers-ro]\naws_access_key_id = GK0000000000000000000000\n"
            "aws_secret_access_key = " + "0" * 64 + "\n",
        ),
        11,
        None,
    ),
]

print(f"clean room: HOME={empty_home}, env scrubbed, interpreter {sys.executable}\n")
failures = []

for label, path, want_rc, want_text in cases:
    rc, last, full = clean_run(path)
    ok = rc == want_rc and (want_text is None or want_text in full)
    print(f"{'ok  ' if ok else 'FAIL'} {label}\n       rc={rc} {last}")
    if not ok:
        failures.append(f"{label}: rc={rc} expected {want_rc}, line={last!r}")
    if rc == 0:
        failures.append(
            f"{label}: READ SUCCEEDED with a broken credential, so the SDK "
            f"fell back to something ambient"
        )

# ── the positive control, which makes the five above mean something ──
rc, last, full = clean_run(REAL)
ok = rc == 0 and "READ_OK" in full
print(f"\n{'ok  ' if ok else 'FAIL'} positive control: the REAL credential in the SAME clean room\n       rc={rc} {last}")
if not ok:
    failures.append(
        "positive control failed, so the clean room itself breaks the read and "
        "the negative results above prove nothing"
    )

print()
if failures:
    for f in failures:
        print("FAILURE:", f)
    raise SystemExit(1)
print("credential access is proven: broken credentials fail loudly, the real one works, "
      "and no ambient fallback exists")
