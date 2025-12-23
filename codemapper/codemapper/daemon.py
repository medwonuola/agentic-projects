import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from codemapper.store import Store, JobStatus
from codemapper.scheduler import Scheduler
from codemapper.processor.parser import CodeParser
from codemapper.processor.cache import HashCache
from codemapper.llm.client import OllamaClient, ModelConfig
from codemapper.utils.gitignore import GitignoreSpec
from codemapper.utils.file_ops import ShadowFS


SOCKET_PATH = Path("/tmp/codemapper.sock")
PID_FILE = Path.home() / ".codemapper" / "daemon.pid"


class MapperEngine:
    def __init__(self, store: Store, ollama: OllamaClient) -> None:
        self._store = store
        self._ollama = ollama
        self._parser = CodeParser()
        self._running_scans: set[str] = set()

    def is_scanning(self, name: str) -> bool:
        return name in self._running_scans

    async def run_scan(self, codebase_id: int, name: str, path: Path) -> tuple[int, int]:
        if name in self._running_scans:
            return 0, 0

        self._running_scans.add(name)
        job_id = str(uuid.uuid4())[:8]

        try:
            await self._store.create_job(job_id, codebase_id, name)

            gitignore = GitignoreSpec(path)
            shadow = ShadowFS(path)
            cache = HashCache(path)
            extensions = {".py", ".js", ".ts", ".tsx", ".rs", ".go"}

            files_processed = 0
            symbols_processed = 0

            await self._store.add_log(job_id, f"Starting scan of {path}")

            if not self._ollama.is_available():
                await self._store.add_log(job_id, "Ollama not available - skipping LLM summaries", "warn")
                await self._store.update_job(job_id, JobStatus.FAILED, 0, 0, "Ollama not available")
                return 0, 0

            source_files: list[Path] = []
            for file_path in path.rglob("*"):
                if file_path.is_dir():
                    continue
                if file_path.suffix not in extensions:
                    continue
                if gitignore.matches(file_path):
                    continue
                lang = self._parser.detect_language(file_path)
                if lang:
                    source_files.append(file_path)

            await self._store.add_log(job_id, f"Found {len(source_files)} source files")

            for file_path in source_files:
                try:
                    lang = self._parser.detect_language(file_path)
                    if not lang:
                        continue

                    content = file_path.read_text()
                    symbols = self._parser.extract_symbols(content, lang)

                    file_summaries: list[str] = []
                    for symbol in symbols:
                        symbol_id = f"{file_path}::{symbol.name}"
                        code_hash = HashCache.compute_hash(symbol.code)

                        if cache.is_changed(symbol_id, code_hash):
                            await self._store.add_log(job_id, f"Processing {symbol.name} in {file_path.name}")
                            try:
                                summary = await self._ollama.summarize_async(symbol)
                                file_summaries.append(f"## {symbol.kind.value.capitalize()}: {symbol.name}\n\n{summary}")
                                cache.update(symbol_id, code_hash, time.time())
                                symbols_processed += 1
                            except Exception as e:
                                await self._store.add_log(job_id, f"LLM error for {symbol.name}: {e}", "error")

                    if file_summaries:
                        map_content = f"# {file_path.name}\n\n" + "\n\n---\n\n".join(file_summaries)
                        shadow.write_map(file_path, map_content)

                    files_processed += 1
                    cache.save()

                except Exception as e:
                    await self._store.add_log(job_id, f"Error processing {file_path.name}: {e}", "error")

            await self._store.update_job(job_id, JobStatus.COMPLETED, symbols_processed, files_processed)
            await self._store.add_log(job_id, f"Completed: {files_processed} files, {symbols_processed} symbols")

        except Exception as e:
            await self._store.update_job(job_id, JobStatus.FAILED, 0, 0, str(e))
            await self._store.add_log(job_id, f"Failed: {e}", "error")

        finally:
            self._running_scans.discard(name)

        return files_processed, symbols_processed


class Daemon:
    def __init__(self) -> None:
        self._store = Store()
        self._scheduler = Scheduler()
        self._ollama = OllamaClient(ModelConfig())
        self._engine = MapperEngine(self._store, self._ollama)
        self._running = False
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        await self._store.init()
        self._scheduler.start()

        codebases = await self._store.get_codebases()
        for cb in codebases:
            self._register_scheduled_job(cb.id, cb.name, Path(cb.path), cb.schedule)

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        self._server = await asyncio.start_unix_server(self._handle_client, path=str(SOCKET_PATH))
        self._running = True

        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

    async def stop(self) -> None:
        self._running = False
        self._scheduler.stop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        if PID_FILE.exists():
            PID_FILE.unlink()

    def _register_scheduled_job(self, codebase_id: int, name: str, path: Path, schedule: str) -> None:
        async def job_func() -> None:
            await self._engine.run_scan(codebase_id, name, path)
        self._scheduler.add_job(f"scan_{name}", schedule, job_func)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(4096)
            request = json.loads(data.decode())
            response = await self._process_command(request)
            writer.write(json.dumps(response).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_command(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd", "")

        if cmd == "ping":
            return {"ok": True, "message": "pong"}

        elif cmd == "scan":
            name = request.get("name", "")
            path = request.get("path", "")
            schedule = request.get("schedule", "")
            cb = await self._store.add_codebase(name, path, schedule)
            self._register_scheduled_job(cb.id, cb.name, Path(cb.path), cb.schedule)
            return {"ok": True, "message": f"Registered {name} with schedule: {schedule}"}

        elif cmd == "run":
            name = request.get("name", "")
            codebases = await self._store.get_codebases()
            for cb in codebases:
                if cb.name == name:
                    if self._engine.is_scanning(name):
                        return {"ok": False, "message": f"Scan already running for {name}"}
                    asyncio.create_task(self._engine.run_scan(cb.id, cb.name, Path(cb.path)))
                    return {"ok": True, "message": f"Started scan for {name}"}
            return {"ok": False, "message": f"Codebase {name} not found. Use 'mapper list' to see registered codebases."}

        elif cmd == "run_once":
            path = request.get("path", "")
            name = Path(path).name
            asyncio.create_task(self._engine.run_scan(0, name, Path(path)))
            return {"ok": True, "message": f"Started one-time scan for {path}"}

        elif cmd == "list":
            codebases = await self._store.get_codebases()
            return {"ok": True, "codebases": [
                {"name": cb.name, "path": cb.path, "schedule": cb.schedule, "last_run": cb.last_run}
                for cb in codebases
            ]}

        elif cmd == "ps":
            jobs = await self._store.get_running_jobs()
            return {"ok": True, "jobs": [
                {"id": j.id, "codebase": j.codebase_name, "status": j.status, "started": j.started_at}
                for j in jobs
            ]}

        elif cmd == "jobs":
            jobs = await self._store.get_jobs(request.get("limit", 20))
            return {"ok": True, "jobs": [
                {"id": j.id, "codebase": j.codebase_name, "status": j.status,
                 "files": j.files_processed, "symbols": j.symbols_processed,
                 "started": j.started_at, "finished": j.finished_at}
                for j in jobs
            ]}

        elif cmd == "logs":
            job_id = request.get("job_id", "")
            logs = await self._store.get_logs(job_id, request.get("limit", 100))
            if not logs:
                jobs = await self._store.get_jobs(50)
                for j in jobs:
                    if j.codebase_name == job_id:
                        logs = await self._store.get_logs(j.id, request.get("limit", 100))
                        break
            return {"ok": True, "logs": [
                {"timestamp": l.timestamp, "level": l.level, "message": l.message}
                for l in logs
            ]}

        elif cmd == "remove":
            name = request.get("name", "")
            self._scheduler.remove_job(f"scan_{name}")
            removed = await self._store.remove_codebase(name)
            return {"ok": removed, "message": f"Removed {name}" if removed else f"{name} not found"}

        elif cmd == "stop":
            asyncio.create_task(self._shutdown())
            return {"ok": True, "message": "Daemon stopping"}

        return {"ok": False, "message": f"Unknown command: {cmd}"}

    async def _shutdown(self) -> None:
        await asyncio.sleep(0.5)
        self._running = False


class DaemonClient:
    @staticmethod
    async def send(cmd: str, **kwargs: Any) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
            request = {"cmd": cmd, **kwargs}
            writer.write(json.dumps(request).encode())
            await writer.drain()
            data = await reader.read(4096)
            writer.close()
            await writer.wait_closed()
            return json.loads(data.decode())
        except (ConnectionRefusedError, FileNotFoundError):
            return {"ok": False, "message": "Daemon not running. Start with: mapper serve"}

    @staticmethod
    def is_running() -> bool:
        return SOCKET_PATH.exists()
