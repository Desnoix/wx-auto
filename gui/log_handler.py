"""
自定义日志处理器 — 广播/订阅模式，支持多个 GUI 面板同时消费。

用法::

    handler = GUIQueueHandler()
    logging.getLogger().addHandler(handler)

    # 每个面板独立订阅一个队列
    my_queue = handler.subscribe()
    while not my_queue.empty():
        record = my_queue.get_nowait()
        # ...更新 GUI
"""

import logging
import queue
import threading
from datetime import datetime


class GUILogRecord:
    """可在 GUI 中显示的格式化日志记录。"""

    __slots__ = ("timestamp", "levelname", "name", "message", "formatted")

    def __init__(self, timestamp: str, levelname: str, name: str,
                 message: str, formatted: str):
        self.timestamp = timestamp
        self.levelname = levelname
        self.name = name
        self.message = message
        self.formatted = formatted


class GUIQueueHandler(logging.Handler):
    """广播式 logging handler：将每条记录复制到所有订阅者队列。"""

    def __init__(self, max_records: int = 2000):
        super().__init__()
        self._max = max_records
        self._subscribers: list[queue.Queue[GUILogRecord]] = []
        self._lock = threading.Lock()
        self._discard_count = 0

    def subscribe(self) -> queue.Queue[GUILogRecord]:
        """为一个消费者创建独立队列。返回的队列由消费者持有。"""
        q: queue.Queue[GUILogRecord] = queue.Queue(maxsize=self._max)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[GUILogRecord]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, record: logging.LogRecord) -> None:
        """将记录广播到所有订阅者。"""
        try:
            timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            formatted = self.format(record)
            gui_record = GUILogRecord(
                timestamp=timestamp,
                levelname=record.levelname,
                name=record.name,
                message=record.getMessage(),
                formatted=formatted,
            )
            with self._lock:
                subs = list(self._subscribers)

            for q in subs:
                try:
                    q.put_nowait(gui_record)
                except queue.Full:
                    with self._lock:
                        self._discard_count += 1
                    # 腾出空间：丢弃最旧的 10%
                    discard_count = max(1, q.qsize() // 10)
                    for _ in range(discard_count):
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break
                    try:
                        q.put_nowait(gui_record)
                    except queue.Full:
                        pass
        except Exception:
            self.handleError(record)

    @property
    def discard_count(self) -> int:
        with self._lock:
            return self._discard_count
