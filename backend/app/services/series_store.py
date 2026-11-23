"""เก็บ Series เป็นไฟล์ JSON (series/<id>/series.json) พร้อมบันทึกเหตุการณ์ให้ wait_events"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from app.services.series_models import Series, SeriesError

SERIES_FILE = "series.json"

logger = logging.getLogger(__name__)


class SeriesStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.load_errors: list[str] = []
        self._series: dict[str, Series] = {}
        self._events: dict[str, list[str]] = {}
        self._changed = threading.Condition(self.lock)

    def load_all(self) -> None:
        """โหลดทุกโฟลเดอร์ใน root; ไฟล์ที่อ่านไม่ได้ถูกข้ามและจดชื่อโฟลเดอร์ไว้ใน load_errors"""
        with self.lock:
            self._series.clear()
            self.load_errors = []
            if not self.root.is_dir():
                return
            for folder in sorted(p for p in self.root.iterdir() if p.is_dir()):
                file = folder / SERIES_FILE
                if not file.is_file():
                    continue
                try:
                    series = Series.model_validate_json(file.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning("ข้ามโฟลเดอร์ซีรีส์ที่อ่านไม่ได้ %s: %s", folder.name, exc)
                    self.load_errors.append(folder.name)
                    continue
                self._series[series.id] = series

    def list(self) -> list[Series]:
        with self.lock:
            return sorted(self._series.values(), key=lambda s: s.created_at)

    def get(self, series_id: str) -> Series:
        with self.lock:
            try:
                return self._series[series_id]
            except KeyError:
                raise SeriesError(f"ไม่พบซีรีส์ '{series_id}'") from None

    def add(self, series: Series) -> None:
        with self.lock:
            self._series[series.id] = series
            self.save(series)

    def save(self, series: Series, event: str | None = None) -> None:
        """เขียน series.json แบบ atomic (ไฟล์ชั่วคราว + os.replace) และแจ้งผู้รอเมื่อมี event"""
        with self.lock:
            series.updated_at = time.time()
            folder = self.series_dir(series.id)
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / (SERIES_FILE + ".tmp")
            tmp.write_text(series.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, folder / SERIES_FILE)
            if event is not None:
                self._events.setdefault(series.id, []).append(event)
                self._changed.notify_all()

    def series_dir(self, series_id: str) -> Path:
        if not series_id or series_id in (".", "..") or any(c in series_id for c in "/\\:"):
            raise SeriesError(f"รหัสซีรีส์ไม่ถูกต้อง: '{series_id}'")
        return self.root / series_id

    def cursor(self, series_id: str) -> int:
        with self.lock:
            return len(self._events.get(series_id, []))

    def wait_events(self, series_id: str, after: int, timeout: float) -> tuple[int, list[str]]:
        """รอจนมี event ใหม่หลังตำแหน่ง after แล้วคืน (cursor ใหม่, events); หมดเวลาคืน (after, [])

        after ที่เกินความยาวบันทึก (เช่น cursor จากก่อน backend รีสตาร์ต) ถูกปรับลงเป็นตำแหน่งปัจจุบัน
        """
        deadline = time.monotonic() + timeout
        with self._changed:
            after = min(after, len(self._events.get(series_id, [])))
            while True:
                events = self._events.get(series_id, [])
                if len(events) > after:
                    return len(events), events[after:]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return after, []
                self._changed.wait(remaining)
