"""
线程安全的任务队列，用于管理未读联系人处理。
保证 FIFO 顺序，防止并发切换会话。
"""

import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatTask:
    """表示待处理的有未读消息的聊天。"""
    contact_name: str
    contact_center: tuple = (0, 0)  # (x, y) 可点击中心
    unread_count: int = 0
    contact_bbox: Optional[list] = None  # OCR bbox [x1,y1,x2,y2]，供 OPEN_CHAT 直接点击


class TaskQueue:
    """ChatTask 的线程安全 FIFO 队列。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: deque[ChatTask] = deque()

    def enqueue(self, contact_name: str, contact_center: tuple = (0, 0),
                unread_count: int = 0, contact_bbox: Optional[list] = None) -> None:
        """向队列添加联系人。"""
        with self._lock:
            self._tasks.append(ChatTask(
                contact_name=contact_name,
                contact_center=contact_center,
                unread_count=unread_count,
                contact_bbox=contact_bbox,
            ))

    def enqueue_task(self, task: ChatTask) -> None:
        """直接添加 ChatTask。"""
        with self._lock:
            self._tasks.append(task)

    def dequeue(self) -> Optional[ChatTask]:
        """从队列取出下一个任务（非阻塞）。

        Returns:
            ChatTask，队列为空时返回 None。
        """
        with self._lock:
            if self._tasks:
                return self._tasks.popleft()
            return None

    def peek(self) -> Optional[ChatTask]:
        """查看下一个任务但不移除。

        Returns:
            ChatTask，队列为空时返回 None。
        """
        with self._lock:
            if self._tasks:
                return self._tasks[0]
            return None

    def is_empty(self) -> bool:
        """检查队列是否为空。"""
        with self._lock:
            return len(self._tasks) == 0

    def size(self) -> int:
        """返回待处理任务数。"""
        with self._lock:
            return len(self._tasks)

    def clear(self) -> None:
        """清空所有待处理任务。"""
        with self._lock:
            self._tasks.clear()

    def contains(self, contact_name: str) -> bool:
        """检查联系人是否已在队列中（防止重复）。

        Args:
            contact_name: 待检查的名称。

        Returns:
            联系人已在队列中返回 True。
        """
        with self._lock:
            return any(task.contact_name == contact_name for task in self._tasks)
