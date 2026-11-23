#!/usr/bin/env python3
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_ORIGIN = "https://leblibrary.co.il"


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
