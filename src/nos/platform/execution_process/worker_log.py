"""Execution log sink in worker process: forwards events to parent via queue + RPC for request_and_wait."""

from __future__ import annotations

import threading
import time
import uuid
from multiprocessing import Event as MpEvent
from multiprocessing import Queue
from queue import Empty
from typing import Any, Optional

from nos.core.execution_log.event_log_buffer import EventLogBuffer
from nos.core.execution_log.events import BaseEvent, CustomEvent

from .serialization import serialize_event


class WorkerQueueLog(EventLogBuffer):
    """
    Buffers events locally and sends each emitted event to the parent process via ``event_q``.

    Uses a multiprocessing ``Event`` for cooperative stop (shared with parent).
    """

    def __init__(
        self,
        event_q: Queue,
        stop_event_mp: MpEvent,
        execution_id: str,
        node_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        module_path: str = "",
        class_name: str = "",
        shared_state: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=workflow_id,
            module_path=module_path,
            class_name=class_name,
            shared_state=shared_state,
            stop_event=threading.Event(),
        )
        self._event_q = event_q
        self._stop_mp = stop_event_mp

    def request_stop(self) -> None:
        self._stop_mp.set()

    def is_stop_requested(self) -> bool:
        return self._stop_mp.is_set()

    def _emit(self, event: BaseEvent) -> None:
        super()._emit(event)
        try:
            self._event_q.put(("emit", serialize_event(event)))
        except Exception:
            pass


class WorkerProxyInteractiveLog(WorkerQueueLog):
    """
    Same as :class:`WorkerQueueLog` but implements ``request_and_wait`` via RPC to the parent
    (parent runs the real Socket.IO handshake).
    """

    is_interactive_worker_proxy: bool = True

    def __init__(
        self,
        event_q: Queue,
        resp_q: Queue,
        stop_event_mp: MpEvent,
        execution_id: str,
        node_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        module_path: str = "",
        class_name: str = "",
        shared_state: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            event_q,
            stop_event_mp,
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=workflow_id,
            module_path=module_path,
            class_name=class_name,
            shared_state=shared_state,
        )
        self._resp_q = resp_q

    def request_and_wait(
        self,
        event_type: str,
        data: dict,
        timeout: float = 60.0,
    ) -> Optional[dict]:
        request_id = str(uuid.uuid4())
        deadline = time.monotonic() + timeout
        self._event_q.put(("rpc_request", request_id, event_type, data))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = self._resp_q.get(timeout=min(remaining, 1.0))
            except Empty:
                continue
            if not msg or len(msg) < 3:
                continue
            if msg[0] == "rpc_response" and msg[1] == request_id:
                return msg[2]


def start_resource_metrics_thread(
    exec_log: WorkerQueueLog,
    interval_s: float = 1.0,
) -> tuple[threading.Event, threading.Thread]:
    """
    Sample RSS + CPU in the worker process and emit ``system_metric`` rows via ``exec_log.log``.

    Returns (stop_flag, thread).
    """
    stop = threading.Event()

    def _run() -> None:
        try:
            import psutil
        except ImportError:
            return
        proc = psutil.Process()
        while not stop.is_set():
            try:
                cpu = proc.cpu_percent(interval=None)
                rss = proc.memory_info().rss
                exec_log.log(
                    "info",
                    "system_metric",
                    event="system_metric",
                    ram_bytes=rss,
                    cpu_percent=cpu,
                )
            except Exception:
                pass
            stop.wait(interval_s)

    t = threading.Thread(target=_run, name="nos-resource-metrics", daemon=True)
    t.start()
    return stop, t
