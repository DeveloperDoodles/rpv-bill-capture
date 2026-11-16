"""
Local records:
  - Audit log: every capture, what OCR read, what was finally saved, and the crop images.
  - Pending queue: bills that could not be written to Google Sheets yet (offline, error).
    They are retried later, so nothing is lost.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional

from .config import LOGS_DIR, PENDING_FILE


class AuditLog:
    def __init__(self, folder: str = LOGS_DIR):
        self.folder = folder
        self.crops = os.path.join(folder, "crops")
        os.makedirs(self.crops, exist_ok=True)

    def _path(self) -> str:
        return os.path.join(self.folder, f"audit-{datetime.now():%Y-%m-%d}.jsonl")

    def save_images(self, images: dict) -> dict:
        """Save crop images, return {name: file path}."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        paths = {}
        for name, img in images.items():
            p = os.path.join(self.crops, f"{stamp}_{name}.png")
            try:
                img.save(p)
                paths[name] = p
            except Exception:
                pass
        return paths

    def record(self, **entry) -> None:
        entry = {"time": datetime.now().isoformat(timespec="seconds"), **entry}
        with open(self._path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class PendingQueue:
    def __init__(self, path: str = PENDING_FILE):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def load(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        items = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return items

    def _save(self, items: list[dict]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    def add(self, bill: dict, timestamp: str, reason: str, allow_duplicate: bool = False) -> dict:
        item = {"id": uuid.uuid4().hex, "bill": bill, "timestamp": timestamp, "reason": reason,
                "allow_duplicate": allow_duplicate}
        items = self.load()
        items.append(item)
        self._save(items)
        return item

    def remove(self, item_id: str) -> None:
        self._save([it for it in self.load() if it["id"] != item_id])

    def update_reason(self, item_id: str, reason: str) -> None:
        items = self.load()
        for it in items:
            if it["id"] == item_id:
                it["reason"] = reason
        self._save(items)

    def find_invoice(self, invoice: str) -> Optional[dict]:
        for it in self.load():
            if it["bill"].get("inv_no") == invoice:
                return it
        return None

    def __len__(self) -> int:
        return len(self.load())
