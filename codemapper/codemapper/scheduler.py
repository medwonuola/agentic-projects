import asyncio
import re
from datetime import datetime, timedelta
from typing import Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


def parse_interval(spec: str) -> timedelta | None:
    match = re.match(r"^every\s+(\d+)\s*(s|m|h|d)$", spec.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return timedelta(**{units[unit]: value})


def is_cron(spec: str) -> bool:
    parts = spec.strip().split()
    return len(parts) == 5 and not spec.startswith("every")


class Scheduler:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def add_job(
        self,
        job_id: str,
        schedule: str,
        func: Callable[[], Awaitable[None]],
    ) -> bool:
        if is_cron(schedule):
            trigger = CronTrigger.from_crontab(schedule)
        else:
            interval = parse_interval(schedule)
            if not interval:
                return False
            trigger = IntervalTrigger(seconds=int(interval.total_seconds()))

        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
        )
        self._jobs[job_id] = schedule
        return True

    def remove_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            del self._jobs[job_id]
            return True
        return False

    def list_jobs(self) -> dict[str, str]:
        return dict(self._jobs)

    def get_next_run(self, job_id: str) -> datetime | None:
        job = self._scheduler.get_job(job_id)
        if job and job.next_run_time:
            return job.next_run_time
        return None
