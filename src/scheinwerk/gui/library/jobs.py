"""Background `sw lib …` jobs (spec §17.9: long jobs never block the window).

Each job is one `sw` subprocess (QProcess), a few at a time. The GUI only reads their output.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QProcess, Signal

PARALLEL = 2


@dataclass
class Job:
    args: list[str]
    on_done: Callable[[Job], None] | None = None
    on_start: Callable[[Job], None] | None = None
    code: int | None = None
    out: str = ""
    err: str = ""
    process: QProcess | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def error(self) -> str:
        """The last `sw: error:` line, or the last line of stderr."""
        lines = [ln for ln in self.err.splitlines() if ln.strip()]
        errors = [ln.removeprefix("sw: error: ") for ln in lines if ln.startswith("sw: error:")]
        return (errors or lines or [f"failed with exit code {self.code}"])[-1]


class JobQueue(QObject):
    """Runs `python -m scheinwerk.cli <args>` jobs, `parallel` at a time, in order."""

    changed = Signal()

    def __init__(self, parallel: int = PARALLEL, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.parallel = parallel
        self.waiting: list[Job] = []
        self.running: list[Job] = []

    def submit(self, args: list[str], on_done=None, on_start=None) -> Job:
        job = Job([str(a) for a in args], on_done, on_start)
        self.waiting.append(job)
        self._next()
        return job

    def cancel(self, job: Job) -> bool:
        """Drop a job that hasn't started. Running jobs finish."""
        if job in self.waiting:
            self.waiting.remove(job)
            self.changed.emit()
            return True
        return False

    @property
    def busy(self) -> bool:
        return bool(self.waiting or self.running)

    def _next(self) -> None:
        while self.waiting and len(self.running) < self.parallel:
            job = self.waiting.pop(0)
            process = QProcess(self)
            job.process = process
            process.finished.connect(lambda code, _status, j=job: self._done(j, code))
            process.errorOccurred.connect(lambda _e, j=job: self._failed_to_start(j))
            self.running.append(job)
            if job.on_start:
                job.on_start(job)
            process.start(sys.executable, ["-m", "scheinwerk.cli", *job.args])
        self.changed.emit()

    def _failed_to_start(self, job: Job) -> None:
        stopped = job.process and job.process.state() == QProcess.ProcessState.NotRunning
        if stopped and job in self.running and job.code is None:
            job.err = job.process.errorString()
            self._done(job, -1)

    def _done(self, job: Job, code: int) -> None:
        if job not in self.running:
            return
        self.running.remove(job)
        if job.process is not None:
            job.out += bytes(job.process.readAllStandardOutput()).decode("utf-8", "replace")
            job.err += bytes(job.process.readAllStandardError()).decode("utf-8", "replace")
            job.process.deleteLater()
            job.process = None
        job.code = code
        if job.on_done:
            job.on_done(job)
        self._next()
