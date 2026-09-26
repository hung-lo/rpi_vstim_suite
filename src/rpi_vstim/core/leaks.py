"""Portable lightweight leak snapshots for software-only campaigns."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LeakSnapshot:
    thread_count: int
    file_descriptor_count: int | None
    child_process_count: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "thread_count": self.thread_count,
            "file_descriptor_count": self.file_descriptor_count,
            "child_process_count": self.child_process_count,
        }


def snapshot() -> LeakSnapshot:
    descriptor_count = None
    descriptor_root = "/dev/fd"
    try:
        descriptor_count = len(os.listdir(descriptor_root))
    except OSError:
        pass
    child_count = None
    children_file = Path("/proc") / str(os.getpid()) / "task" / str(os.getpid()) / "children"
    try:
        child_count = len(children_file.read_text(encoding="ascii").split())
    except OSError:
        pass
    return LeakSnapshot(len(threading.enumerate()), descriptor_count, child_count)


def delta(before: LeakSnapshot, after: LeakSnapshot) -> dict[str, int | None]:
    fd_delta = None
    if before.file_descriptor_count is not None and after.file_descriptor_count is not None:
        fd_delta = after.file_descriptor_count - before.file_descriptor_count
    child_delta = None
    if before.child_process_count is not None and after.child_process_count is not None:
        child_delta = after.child_process_count - before.child_process_count
    return {
        "thread_delta": after.thread_count - before.thread_count,
        "file_descriptor_delta": fd_delta,
        "child_process_delta": child_delta,
    }
