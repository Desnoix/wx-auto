"""
线程安全的任务队列，用于管理未读联系人处理。
保证 FIFO 顺序，防止并发切换会话。
"""

import queue as _queue
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatTask:
    """表示待处理的有未读消息的聊天。"""
    contact_name: str
    contact_center: tuple = (0, 0)  # (x, y) 可点击中心
    unread_count: int = 0


class TaskQueue:
    """ChatTask 的线程安全 FIFO 队列。"""

    def __init__(self):
        self._queue = _queue.Queue()

    def enqueue(self, contact_name: str, contact_center: tuple = (0, 0),
                unread_count: int = 0) -> None:
        """向队列添加联系人。

        Args:
            contact_name: 联系人/聊天名称。
            contact_center: 可点击坐标 (x, y)。
            unread_count: 未读消息数。
        """
        self._queue.put(ChatTask(
            contact_name=contact_name,
            contact_center=contact_center,
            unread_count=unread_count
        ))

    def enqueue_task(self, task: ChatTask) -> None:
        """直接添加 ChatTask。"""
        self._queue.put(task)

    def dequeue(self) -> Optional[ChatTask]:
        """从队列取出下一个任务（非阻塞）。

        Returns:
            ChatTask，队列为空时返回 None。
        """
        try:
            return self._queue.get_nowait()
        except _queue.Empty:
            return None

    def peek(self) -> Optional[ChatTask]:
        """查看下一个任务但不移除。

        Returns:
            ChatTask，队列为空时返回 None。
        """
        with self._queue.mutex:
            if self._queue.empty():
                return None
            return self._queue.queue[0]

    def is_empty(self) -> bool:
        """检查队列是否为空。"""
        return self._queue.empty()

    def size(self) -> int:
        """返回待处理任务数。"""
        return self._queue.qsize()

    def clear(self) -> None:
        """清空所有待处理任务。"""
        with self._queue.mutex:
            self._queue.queue.clear()

    def contains(self, contact_name: str) -> bool:
        """检查联系人是否已在队列中（防止重复）。

        Args:
            contact_name: 待检查的名称。

        Returns:
            联系人已在队列中返回 True。
        """
        with self._queue.mutex:
            for task in self._queue.queue:
                if task.contact_name == contact_name:
                    return True
        return False