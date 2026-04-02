"""
MES/ERP integration event bus for SENIA Elite.

Publishes quality events to external systems via:
  - Webhooks (HTTP POST)
  - File-based queue (for offline/batch integration)
  - Pluggable backends (message queues, etc.)

Events are typed and include full context for downstream processing.

Usage:
    bus = EventBus()
    bus.add_subscriber(WebhookSubscriber("http://mes.local/api/quality"))
    bus.add_subscriber(FileQueueSubscriber(Path("./event_queue")))

    bus.publish(QualityDecisionEvent(
        lot_id="L001",
        decision="AUTO_RELEASE",
        avg_delta_e=0.85,
    ))
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Protocol


# ─── Event Types ──────────────────────────────────────────

@dataclass
class BaseEvent:
    event_type: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    source: str = "senia-elite"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityDecisionEvent(BaseEvent):
    event_type: str = "quality_decision"
    lot_id: str = ""
    line_id: str = ""
    product_code: str = ""
    customer_id: str = ""
    decision: str = ""
    avg_delta_e: float = 0.0
    p95_delta_e: float = 0.0
    confidence: float = 0.0
    profile: str = ""
    operator_id: str = ""


@dataclass
class CalibrationEvent(BaseEvent):
    event_type: str = "calibration"
    action: str = ""  # "started", "completed", "overdue", "failed"
    source_type: str = ""  # "ccm", "gray_card", "colorchecker"
    details: str = ""


@dataclass
class DriftAlertEvent(BaseEvent):
    event_type: str = "drift_alert"
    lot_id: str = ""
    line_id: str = ""
    drift_magnitude: float = 0.0
    direction: str = ""
    recommended_action: str = ""


@dataclass
class BatchCompleteEvent(BaseEvent):
    event_type: str = "batch_complete"
    batch_id: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    avg_delta_e: float = 0.0
    elapsed_sec: float = 0.0


# ─── Subscriber Protocol & Implementations ────────────────

class EventSubscriber(Protocol):
    """Interface for event subscribers."""
    def handle(self, event: dict[str, Any]) -> bool: ...


class WebhookSubscriber:
    """Publish events via HTTP POST to a webhook URL."""

    def __init__(
        self,
        url: str,
        timeout_sec: int = 5,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout_sec
        self._headers = headers or {}

    def handle(self, event: dict[str, Any]) -> bool:
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        hdrs = {"Content-Type": "application/json", **self._headers}
        req = urllib.request.Request(self._url, data=payload, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status < 400
        except (urllib.error.URLError, TimeoutError, OSError):
            return False


class FileQueueSubscriber:
    """Append events to a JSONL file for offline/batch consumption."""

    def __init__(self, queue_dir: Path) -> None:
        self._dir = queue_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def handle(self, event: dict[str, Any]) -> bool:
        date_str = time.strftime("%Y%m%d")
        file_path = self._dir / f"events_{date_str}.jsonl"
        line = json.dumps(event, ensure_ascii=False)
        with self._lock:
            try:
                with file_path.open("a", encoding="utf-8") as fp:
                    fp.write(line + "\n")
                return True
            except OSError:
                return False

    def read_pending(self, max_count: int = 500) -> list[dict[str, Any]]:
        """Read recent events from the queue files."""
        events: list[dict[str, Any]] = []
        for jsonl in sorted(self._dir.glob("events_*.jsonl"), reverse=True):
            with jsonl.open("r", encoding="utf-8") as fp:
                for line in fp:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        events.append(json.loads(text))
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if len(events) >= max_count:
                        return events
        return events


# ─── Event Bus ─────────────────────────────────────────────

class EventBus:
    """Central event dispatcher with async delivery."""

    def __init__(self, async_delivery: bool = True) -> None:
        self._subscribers: list[EventSubscriber] = []
        self._lock = RLock()
        self._async = async_delivery
        self._dead_letters: list[dict[str, Any]] = []
        self._max_dead_letters = 1000

    def add_subscriber(self, subscriber: EventSubscriber) -> None:
        with self._lock:
            self._subscribers.append(subscriber)

    def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribers."""
        data = event.to_dict()
        if self._async:
            thread = Thread(target=self._deliver, args=(data,), daemon=True)
            thread.start()
        else:
            self._deliver(data)

    def publish_dict(self, event: dict[str, Any]) -> None:
        """Publish a raw dict event to all subscribers."""
        if self._async:
            thread = Thread(target=self._deliver, args=(event,), daemon=True)
            thread.start()
        else:
            self._deliver(event)

    def get_dead_letters(self) -> list[dict[str, Any]]:
        """Return events that failed delivery to all subscribers."""
        with self._lock:
            return list(self._dead_letters)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _deliver(self, data: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subscribers)

        all_failed = True
        for sub in subs:
            try:
                if sub.handle(data):
                    all_failed = False
            except Exception:
                continue

        if all_failed and subs:
            with self._lock:
                self._dead_letters.append(data)
                if len(self._dead_letters) > self._max_dead_letters:
                    self._dead_letters = self._dead_letters[-self._max_dead_letters:]
