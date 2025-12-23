import aiosqlite
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Codebase:
    id: int
    name: str
    path: str
    schedule: str
    created_at: str
    last_run: str | None = None


@dataclass
class Job:
    id: str
    codebase_id: int
    codebase_name: str
    status: JobStatus
    started_at: str
    finished_at: str | None = None
    symbols_processed: int = 0
    files_processed: int = 0
    error: str | None = None


@dataclass
class LogEntry:
    job_id: str
    timestamp: str
    message: str
    level: str = "info"


class Store:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or Path.home() / ".codemapper" / "mapper.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS codebases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    path TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_run TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    codebase_id INTEGER NOT NULL,
                    codebase_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    symbols_processed INTEGER DEFAULT 0,
                    files_processed INTEGER DEFAULT 0,
                    error TEXT,
                    FOREIGN KEY (codebase_id) REFERENCES codebases(id)
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    message TEXT NOT NULL,
                    level TEXT DEFAULT 'info',
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_codebase ON jobs(codebase_id);
                CREATE INDEX IF NOT EXISTS idx_logs_job ON logs(job_id);
            """)
            await db.commit()

    async def add_codebase(self, name: str, path: str, schedule: str) -> Codebase:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT OR REPLACE INTO codebases (name, path, schedule, created_at) VALUES (?, ?, ?, ?)",
                (name, path, schedule, datetime.now().isoformat())
            )
            await db.commit()
            return Codebase(
                id=cursor.lastrowid or 0,
                name=name,
                path=path,
                schedule=schedule,
                created_at=datetime.now().isoformat()
            )

    async def get_codebases(self) -> list[Codebase]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM codebases ORDER BY name")
            rows = await cursor.fetchall()
            return [Codebase(**dict(row)) for row in rows]

    async def remove_codebase(self, name: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM codebases WHERE name = ?", (name,))
            await db.commit()
            return cursor.rowcount > 0

    async def create_job(self, job_id: str, codebase_id: int, codebase_name: str) -> Job:
        job = Job(
            id=job_id,
            codebase_id=codebase_id,
            codebase_name=codebase_name,
            status=JobStatus.RUNNING,
            started_at=datetime.now().isoformat()
        )
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO jobs (id, codebase_id, codebase_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
                (job.id, job.codebase_id, job.codebase_name, job.status, job.started_at)
            )
            await db.commit()
        return job

    async def update_job(self, job_id: str, status: JobStatus, symbols: int = 0, files: int = 0, error: str | None = None) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            finished = datetime.now().isoformat() if status in (JobStatus.COMPLETED, JobStatus.FAILED) else None
            await db.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, symbols_processed = ?, files_processed = ?, error = ? WHERE id = ?",
                (status, finished, symbols, files, error, job_id)
            )
            await db.execute(
                "UPDATE codebases SET last_run = ? WHERE id = (SELECT codebase_id FROM jobs WHERE id = ?)",
                (datetime.now().isoformat(), job_id)
            )
            await db.commit()

    async def get_jobs(self, limit: int = 20) -> list[Job]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [Job(**{**dict(row), "status": JobStatus(row["status"])}) for row in rows]

    async def get_running_jobs(self) -> list[Job]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY started_at DESC",
                (JobStatus.RUNNING,)
            )
            rows = await cursor.fetchall()
            return [Job(**{**dict(row), "status": JobStatus(row["status"])}) for row in rows]

    async def add_log(self, job_id: str, message: str, level: str = "info") -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO logs (job_id, timestamp, message, level) VALUES (?, ?, ?, ?)",
                (job_id, datetime.now().isoformat(), message, level)
            )
            await db.commit()

    async def get_logs(self, job_id: str, limit: int = 100) -> list[LogEntry]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT job_id, timestamp, message, level FROM logs WHERE job_id = ? ORDER BY timestamp ASC LIMIT ?",
                (job_id, limit)
            )
            rows = await cursor.fetchall()
            return [LogEntry(**dict(row)) for row in rows]
