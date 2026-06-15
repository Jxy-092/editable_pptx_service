from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Task:
    id: str
    status: str = "PENDING"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    progress: Dict[str, Any] = field(default_factory=dict)

    def set_progress(self, progress: Dict[str, Any]):
        self.progress = progress
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.id,
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
            "completed_at": self.completed_at.isoformat() + "Z" if self.completed_at else None,
            "error_message": self.error_message,
            "progress": self.progress,
        }


class TaskStore:
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, task_id: str) -> Task:
        with self._lock:
            task = Task(id=task_id)
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs) -> Optional[Task]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            for key, value in kwargs.items():
                setattr(task, key, value)
            task.updated_at = datetime.utcnow()
            return task


TASK_STORE = TaskStore()
