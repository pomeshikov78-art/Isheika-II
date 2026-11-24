"""Резервное копирование и восстановление (ROADMAP P6, регламент эксплуатации).

Копия — это ZIP с согласованным снимком БД (sqlite backup API, корректно при
WAL), зашифрованным хранилищем ключей, конфигурацией и манифестом с
контрольными суммами. Восстановление:

* требует явного подтверждения (без него — E_STATE);
* проверяет копию ДО записи (CRC, суммы, integrity_check, состав схемы);
* автоматически снимает копию текущего состояния (kind="pre-restore"),
  чтобы откат был возможен всегда;
* выполняется при остановленном сервере — из CLI (`run.py --restore ... --yes`).

Ключи шифруются на сервере (ТЗ-01 §11) и в копию попадают в зашифрованном виде;
мастер-ключ в копию НЕ включается: без него копия бесполезна для постороннего.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

from . import __version__
from .config import DATA_DIR, SETTINGS
from .contracts import CoreError, iso_now, new_id
from .storage import db

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
COUNTED_TABLES = ("core_researches", "content_documents", "content_occurrences",
                  "knowledge_claims", "evidence_items", "workflow_jobs", "audit_log")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_db(dest: str) -> None:
    """Согласованный снимок БД через sqlite backup API (не копирование файла)."""
    src = db.connect()
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()


def _counts() -> dict:
    out = {}
    for t in COUNTED_TABLES:
        try:
            out[t] = db.count(t)
        except Exception:
            out[t] = None
    return out


def create(*, actor: str = "system", kind: str = "manual", dest_dir: str | None = None) -> dict:
    """Создание резервной копии. Возвращает запись реестра копий."""
    SETTINGS.ensure_dirs()
    folder = dest_dir or BACKUP_DIR
    os.makedirs(folder, exist_ok=True)
    bid = new_id("bkp-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(folder, f"isheika-backup-{stamp}-{bid[-6:]}.zip")
    tmp = tempfile.mkdtemp(prefix="isheika-backup-")
    try:
        dbfile = os.path.join(tmp, "isheika.db")
        _snapshot_db(dbfile)
        payload = {"isheika.db": dbfile}
        for name, src in (("secrets.enc", SETTINGS.secrets_path),
                          ("config.json", os.path.join(DATA_DIR, "config.json"))):
            if os.path.exists(src):
                dst = os.path.join(tmp, name)
                shutil.copy2(src, dst)
                payload[name] = dst
        migrations = [r["version"] for r in db.query("SELECT version FROM meta_migrations ORDER BY version")]
        manifest = {
            "format": "isheika-backup-1", "backup_id": bid, "kind": kind,
            "created_at": iso_now(), "created_by": actor,
            "app_version": __version__, "python_schema": migrations,
            "counts": _counts(),
            "files": {n: {"bytes": os.path.getsize(p), "sha256": _sha256_file(p)} for n, p in payload.items()},
            "note": "Мастер-ключ шифрования ключей в копию не включается.",
        }
        mpath = os.path.join(tmp, "manifest.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name, p in list(payload.items()) + [("manifest.json", mpath)]:
                z.write(p, name)
        row = {"id": bid, "created_at": manifest["created_at"], "path": path,
               "file_name": os.path.basename(path), "size_bytes": os.path.getsize(path),
               "sha256": _sha256_file(path), "kind": kind, "app_version": __version__,
               "items": manifest["files"], "created_by": actor}
        db.insert("ops_backups", row)
        return db.dec(row, "items")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify(path: str, *, register: bool = True) -> dict:
    """Проверка копии: CRC, контрольные суммы, целостность БД, состав схемы."""
    if not os.path.exists(path):
        raise CoreError("E_NOT_FOUND", f"Копия не найдена: {path}")
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = ""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    tmp = tempfile.mkdtemp(prefix="isheika-verify-")
    manifest: dict = {}
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            add("zip_crc", bad is None, f"повреждён: {bad}" if bad else "все записи читаемы")
            names = z.namelist()
            add("manifest_present", "manifest.json" in names)
            if "manifest.json" in names:
                manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            add("database_present", "isheika.db" in names)
            for name, meta in (manifest.get("files") or {}).items():
                if name not in names:
                    add(f"file:{name}", False, "отсутствует в архиве")
                    continue
                data = z.read(name)
                digest = hashlib.sha256(data).hexdigest()
                add(f"sha256:{name}", digest == meta.get("sha256"),
                    f"{len(data)} Б, сумма {'совпала' if digest == meta.get('sha256') else 'НЕ совпала'}")
            if "isheika.db" in names:
                z.extract("isheika.db", tmp)
        dbpath = os.path.join(tmp, "isheika.db")
        if os.path.exists(dbpath):
            conn = sqlite3.connect(dbpath)
            try:
                state = conn.execute("PRAGMA integrity_check").fetchone()[0]
                add("db_integrity", state == "ok", str(state))
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                need = {"core_researches", "meta_migrations"}
                add("db_schema", need.issubset(tables), f"таблиц: {len(tables)}")
                rows = conn.execute("SELECT COUNT(*) FROM core_researches").fetchone()[0]
                declared = (manifest.get("counts") or {}).get("core_researches")
                add("db_counts", declared is None or rows == declared,
                    f"исследований в копии: {rows}, в манифесте: {declared}")
            finally:
                conn.close()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        add("zip_readable", False, f"{type(exc).__name__}: {exc}")
    except Exception as exc:                       # повреждённый поток сжатия и т.п.
        add("zip_readable", False, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(c["ok"] for c in checks)
    result = {"path": path, "ok": ok, "checks": checks, "manifest": manifest,
              "verified_at": iso_now(), "sha256": _sha256_file(path)}
    if register:
        row = db.one("SELECT * FROM ops_backups WHERE path=?", (path,))
        if row:
            db.update("ops_backups", "id", row["id"],
                      {"verified_at": result["verified_at"], "verify_result": {"ok": ok, "checks": checks}})
    return result


def list_backups() -> list[dict]:
    rows = db.query("SELECT * FROM ops_backups ORDER BY created_at DESC LIMIT 200")
    out = []
    for r in rows:
        r = db.dec(r, "items", "verify_result")
        r["exists"] = os.path.exists(r["path"])
        out.append(r)
    return out


def resolve(backup_id: str) -> str:
    row = db.one("SELECT path FROM ops_backups WHERE id=? OR file_name=?", (backup_id, backup_id))
    if row:
        return row["path"]
    if os.path.exists(backup_id):
        return backup_id
    raise CoreError("E_NOT_FOUND", f"Копия не найдена: {backup_id}")


def restore(path: str, *, actor: str = "system", confirm: bool = False) -> dict:
    """Восстановление состояния из копии. Только при остановленном сервере."""
    if not confirm:
        raise CoreError("E_STATE", "Восстановление требует явного подтверждения (--yes / confirm=true)")
    path = resolve(path)
    check = verify(path, register=False)
    if not check["ok"]:
        raise CoreError("E_VALIDATION", "Копия не прошла проверку: " +
                        "; ".join(c["check"] for c in check["checks"] if not c["ok"]))
    safety = create(actor=actor, kind="pre-restore")
    tmp = tempfile.mkdtemp(prefix="isheika-restore-")
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        db.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            target = SETTINGS.db_path + suffix
            src = os.path.join(tmp, "isheika.db") if not suffix else None
            if src and os.path.exists(src):
                shutil.copy2(src, target)
            elif os.path.exists(target):
                os.remove(target)
        for name, target in (("secrets.enc", SETTINGS.secrets_path),
                             ("config.json", os.path.join(DATA_DIR, "config.json"))):
            src = os.path.join(tmp, name)
            if os.path.exists(src):
                shutil.copy2(src, target)
        db.init_db()
        restored = _counts()
        from .workflow import events
        events.emit("system.warning", payload={"action": "backup.restore", "source": path,
                                               "safety_backup": safety["id"], "counts": restored},
                    severity="warning")
        return {"restored_from": path, "safety_backup": safety, "counts": restored,
                "manifest": check["manifest"], "restored_at": iso_now(), "actor": actor}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
