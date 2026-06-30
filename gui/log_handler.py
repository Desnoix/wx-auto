"""
自定义日志处理器 — 捕获日志记录并放入线程安全队列，
供 GUI 面板实时消费。
"""

import logging
import queue
import threading
from datetime import datetime
from typing import Optional


class GUILogRecord:
    """可在 GUI 中显示的格式化日志记录。"""

    __slots__ = ("timestamp", "levelname", "name", "message", "formatted")

    def __init__(self, timestamp: str, levelname: str, name: str, message: str, formatted: str):
        self.timestamp = timestamp
        self.levelname = levelname
        self.name = name
        self.message = message
        self.formatted = formatted


class GUIQueueHandler(logging.Handler):
    """将日志记录放入队列的 logging handler。

    用法::

        handler = GUIQueueHandler()
        logging.getLogger().addHandler(handler)
        # 然后在 GUI 线程中:
        while not handler.queue.empty():
            record = handler.queue.get_nowait()
            # 更新 GUI
    """

    def __init__(self, max_records: int = 1000):
        super().__init__()
        self.queue: queue.Queue[GUILogRecord] = queue.Queue(maxsize=max_records)
        self._lock = threading.Lock()
        self._discard_count = 0

    def emit(self, record: logging.LogRecord) -> None:
        """格式化并放入队列。如果队列满则丢弃最旧记录。"""
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
            # 非阻塞放入，满则丢弃
            try:
                self.queue.put_nowait(gui_record)
            except queue.Full:
                with self._lock:
                    self._discard_count += 1
                    # 腾出空间：丢弃最旧的 10%
                    discard_count = max(1, self.queue.qsize() // 10)
                    for _ in range(discard_count):
                        try:
                            self.queue.get_nowait()
                        except queue.Empty:
                            break
                    self.queue.put_nowait(gui_record)
        except Exception:
            self.handleError(record)

    def get_all(self) -> list[GUILogRecord]:
        """取出队列中所有记录（非阻塞）。"""
        records: list[GUILogRecord] = []
        while not self.queue.empty():
            try:
                records.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return records

    @property
    def discard_count(self) -> int:
        with self._lock:
            return self._discard_count