#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from collections import Counter
from io import StringIO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DJANGO_READY = False


def bootstrap_django():
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    import django
    django.setup()
    _DJANGO_READY = True


def run_checks():
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_mig_01_graph():
        bootstrap_django()
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader
        try:
            loader = MigrationLoader(connection, ignore_no_migrations=False)
            leaves = loader.graph.leaf_nodes("articles")
            ok = len(leaves) == 1
            return ok, f"articles_leaf_nodes={leaves}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    ok, det = chk_mig_01_graph()
    record("MIG-01", "Migration graph loads cleanly with a single articles head (no missing parents or branches)", ok, det)

    def chk_mig_02_db_history():
        bootstrap_django()
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        try:
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            ok = len(plan) == 0
            return ok, f"unapplied_migrations={len(plan)}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    ok, det = chk_mig_02_db_history()
    record("MIG-02", "Database migration history is consistent and all migrations are applied", ok, det)

    def chk_mig_03_models_sync():
        bootstrap_django()
        from django.core.management import call_command
        buf = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=buf, stderr=buf)
            return True, "models_in_sync=True"
        except SystemExit as exc:
            out = buf.getvalue().strip().splitlines()
            tail = " | ".join(out[-3:]) if out else f"exit={exc.code}"
            return False, tail
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    ok, det = chk_mig_03_models_sync()
    record("MIG-03", "models.py matches migrations with zero unmigrated changes", ok, det)

    def chk_mig_04_git_and_prefixes():
        mig_dir = os.path.join(BASE_DIR, "articles", "migrations")
        disk_files = sorted(
            f for f in os.listdir(mig_dir)
            if f.endswith(".py") and f != "__init__.py"
        )
        prefixes = [m.group(1) for f in disk_files for m in [re.match(r"^(\d+)_", f)] if m]
        dup_prefixes = [p for p, cnt in Counter(prefixes).items() if cnt > 1]

        proc_ls = subprocess.run(
            ["git", "ls-files", "articles/migrations/"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        proc_st = subprocess.run(
            ["git", "status", "--porcelain", "articles/migrations/"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        tracked = {
            os.path.basename(line.strip())
            for line in proc_ls.stdout.splitlines()
            if line.strip().endswith(".py") and os.path.basename(line.strip()) != "__init__.py"
        }
        disk_set = set(disk_files)
        untracked = sorted(disk_set - tracked)
        missing_on_disk = sorted(tracked - disk_set)
        dirty_git = [line.strip() for line in proc_st.stdout.splitlines() if line.strip()]
        ok = (
            bool(disk_files)
            and not dup_prefixes
            and not untracked
            and not missing_on_disk
            and not dirty_git
            and proc_ls.returncode == 0
            and proc_st.returncode == 0
        )
        return ok, f"disk={len(disk_files)}, tracked={len(tracked)}, dup_prefixes={dup_prefixes}, untracked={untracked}, missing_on_disk={missing_on_disk}, dirty_git={len(dirty_git)}"

    ok, det = chk_mig_04_git_and_prefixes()
    record("MIG-04", "Git index and disk match 1:1 in articles/migrations with unique sequential prefixes", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY MIGRATIONS INTEGRITY VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {code:<10} | {label}")
        if det:
            print(f"         -> {det}")
    print("=" * 84 + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run_checks()