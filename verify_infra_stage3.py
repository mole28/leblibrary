#!/usr/bin/env python3
import glob
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_ORIGIN = "https://leblibrary.co.il"
BACKUP_DIR = "/root/backups/leblibrary"


def fetch(path, method="GET", data=None, headers=None, timeout=20):
    req_headers = {"User-Agent": "LebLibrary-InfraVerifier/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(LIVE_ORIGIN + path, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, dict(exc.headers.items()), body


def check_backup_restore_readiness():
    if not os.path.isdir(BACKUP_DIR):
        return False, f"backup_dir_missing={BACKUP_DIR}"

    data_archives = sorted(glob.glob(os.path.join(BACKUP_DIR, "leblibrary_backup_*_data.tar.gz")), reverse=True)
    if not data_archives:
        return False, "no_data_backup_found"

    latest_data = data_archives[0]
    prefix = latest_data[:-len("_data.tar.gz")]
    sha_file = prefix + ".sha256"
    enc_env = prefix + "_env.tar.gz.enc"
    plain_env = prefix + ".env.plain"

    if not os.path.isfile(sha_file):
        return False, f"missing_sha256={os.path.basename(sha_file)}"
    if not (os.path.isfile(enc_env) or os.path.isfile(plain_env)):
        return False, "missing_env_backup"

    chk = subprocess.run(
        ["sha256sum", "-c", os.path.basename(sha_file)],
        cwd=BACKUP_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if chk.returncode != 0:
        return False, f"sha256_failed={chk.stdout.strip() or chk.stderr.strip()}"

    tmp_dir = tempfile.mkdtemp(prefix="leb_verify_restore_")
    try:
        with tarfile.open(latest_data, "r:gz") as tf:
            tf.extractall(path=tmp_dir, filter="data")

        db_path = os.path.join(tmp_dir, "db.sqlite3")
        if not os.path.isfile(db_path):
            return False, "restored_db_missing"

        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            integ = conn.execute("PRAGMA integrity_check;").fetchone()
        finally:
            conn.close()
        if not integ or str(integ[0]).lower() != "ok":
            return False, f"sqlite_integrity={integ}"

        chroma_info = "none"
        chroma_path = os.path.join(tmp_dir, "chroma_db")
        if os.path.isdir(chroma_path):
            try:
                from chromadb import PersistentClient
                client = PersistentClient(path=chroma_path)
                cols = client.list_collections()
                col_names = [getattr(c, "name", str(c)) for c in cols]
                chroma_info = f"collections={len(col_names)}({','.join(col_names[:3])})"
            except Exception as exc:
                return False, f"chroma_restore_failed={exc}"

        env_status = "plain_ok" if os.path.isfile(plain_env) else "enc_present"
        passphrase = os.environ.get("BACKUP_PASSPHRASE", "")
        if os.path.isfile(enc_env) and passphrase:
            dec = subprocess.run(
                [
                    "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
                    "-iter", "200000", "-pass", f"pass:{passphrase}", "-in", enc_env
                ],
                capture_output=True,
                check=False,
            )
            if dec.returncode != 0:
                return False, "env_decrypt_failed"
            env_tar_path = os.path.join(tmp_dir, "_env_check.tar.gz")
            with open(env_tar_path, "wb") as ef:
                ef.write(dec.stdout)
            with tarfile.open(env_tar_path, "r:gz") as etf:
                etf.extractall(path=tmp_dir, filter="data")
            os.remove(env_tar_path)
            if not os.path.isfile(os.path.join(tmp_dir, ".env")):
                return False, "decrypted_env_missing"
            env_status = "enc_decrypted_ok"

        data_mb = round(os.path.getsize(latest_data) / (1024 * 1024), 1)
        db_mb = round(os.path.getsize(db_path) / (1024 * 1024), 1)
        media_exists = os.path.isdir(os.path.join(tmp_dir, "media"))
        detail = (
            f"archive={os.path.basename(latest_data)} ({data_mb}MB), "
            f"db={db_mb}MB (ok), media={media_exists}, {chroma_info}, env={env_status}"
        )
        return True, detail
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_checks():
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    code, hdrs, _ = fetch("/", method="HEAD")
    h = {k.lower(): v for k, v in hdrs.items()}
    ok_hdrs = (
        code == 200
        and h.get("server", "").strip().lower() == "nginx"
        and "content-security-policy" in h
        and "permissions-policy" in h
        and "strict-transport-security" in h
        and h.get("x-frame-options", "").upper() == "DENY"
    )
    record("INFRA-01", "Nginx hides version and enforces CSP, Permissions-Policy, HSTS, X-Frame-Options", ok_hdrs, f"http={code}, server={h.get('server')}, csp={'content-security-policy' in h}")

    c_env, _, _ = fetch("/.env", method="HEAD")
    c_db, _, _ = fetch("/db.sqlite3", method="HEAD")
    record("INFRA-02", "Nginx blocks /.env and /db.sqlite3 with HTTP 403", c_env == 403 and c_db == 403, f"/.env={c_env}, /db.sqlite3={c_db}")

    c_gz, h_gz, _ = fetch("/manifest.json", method="HEAD", headers={"Accept-Encoding": "gzip"})
    gz_enc = {k.lower(): v for k, v in h_gz.items()}.get("content-encoding", "")
    record("INFRA-03", "Nginx serves Gzip compression on JSON endpoints", c_gz == 200 and "gzip" in gz_enc.lower(), f"http={c_gz}, content-encoding={gz_enc}")

    ps = subprocess.run(["ps", "-eo", "user,cmd"], capture_output=True, text=True, check=False)
    g_users = sorted({line.split()[0] for line in ps.stdout.splitlines() if "gunicorn" in line and "core.wsgi" in line})
    record("INFRA-04", "Gunicorn workers run strictly as non-root www-data", g_users == ["www-data"], f"gunicorn_users={g_users}")

    env_path = os.path.join(BASE_DIR, ".env")
    st_mode = oct(stat.S_IMODE(os.stat(env_path).st_mode)) if os.path.exists(env_path) else "missing"
    dup_env = os.path.exists(os.path.join(BASE_DIR, "articles", ".env"))
    pii_jsonl = os.path.exists(os.path.join(BASE_DIR, "contact_messages_backup.jsonl"))
    ok_fs = st_mode == "0o600" and not dup_env and not pii_jsonl
    record("INFRA-05", ".env is chmod 600 with no duplicate articles/.env or PII .jsonl file", ok_fs, f"mode={st_mode}, dup_env={dup_env}, pii_jsonl={pii_jsonl}")

    c_qa, _, b_qa = fetch(
        "/api/ai-chat/",
        method="POST",
        data=json.dumps({"question": "\u05e2\u05dc \u05e9\u05d4\u05e0\u05d7\u05dc\u05ea \u05dc\u05e0\u05d5 \u05d5\u05dc\u05d0\u05d1\u05d5\u05ea\u05d9\u05e0\u05d5?", "mode": "qa"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": LIVE_ORIGIN},
        timeout=30,
    )
    ok_qa = c_qa == 200 and len(b_qa) > 80 and "\u05e9\u05d2\u05d9\u05d0\u05ea \u05ea\u05e7\u05e9\u05d5\u05e8\u05ea" not in b_qa
    record("INFRA-06", "Live academic AI QA chat (ChromaDB + Gemini) returns real response", ok_qa, f"http={c_qa}, len={len(b_qa)}")

    ok_bk, det_bk = check_backup_restore_readiness()
    record("INFRA-07", "Latest backup passes SHA-256, SQLite integrity, ChromaDB collections & restore check", ok_bk, det_bk)

    passed = sum(1 for _, _, ok, _ in results if ok)
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY INFRASTRUCTURE & LIVE QA VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {code:<10} | {label}")
        if det:
            print(f"         -> {det}")
    print("=" * 84 + "\n")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    run_checks()
