from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Callable


DEFAULT_SCHEMAS: dict[str, list[str]] = {
    "campus_configs.csv": ["campus", "weekday_quota", "rest_day_quota", "enabled", "instruction"],
    "reservations.csv": [
        "reservation_id",
        "name",
        "employee_id",
        "mobile",
        "campus",
        "reservation_date",
        "plate_no",
        "status",
    ],
    "ketuo_reservation_archive.csv": ["reservation_id", "plate_no", "campus", "reserve_date", "status", "remark"],
    "payment_records.csv": ["payment_id", "reservation_id", "plate_no", "amount", "status", "created_at"],
    "internal_vehicle_archive.csv": ["plate_no", "owner", "remark"],
}


class CSVRepository:
    def __init__(self, base_dir: Path | str = "data", schemas: dict[str, list[str]] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.schemas = schemas or DEFAULT_SCHEMAS
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        for table, headers in self.schemas.items():
            path = self.path_for(table)
            if not path.exists():
                self._atomic_write(path, [], headers)

    def path_for(self, table: str) -> Path:
        if table not in self.schemas:
            raise ValueError(f"Unknown CSV table: {table}")
        return self.base_dir / table

    def read_all(self, table: str) -> list[dict[str, str]]:
        path = self.path_for(table)
        if not path.exists():
            self._atomic_write(path, [], self.schemas[table])
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def query(self, table: str, predicate: Callable[[dict[str, str]], bool]) -> list[dict[str, str]]:
        return [row for row in self.read_all(table) if predicate(row)]

    def append(self, table: str, row: dict[str, object]) -> dict[str, str]:
        rows = self.read_all(table)
        normalized = self._normalize(table, row)
        rows.append(normalized)
        self._atomic_write(self.path_for(table), rows, self.schemas[table])
        return normalized

    def update(self, table: str, predicate: Callable[[dict[str, str]], bool], changes: dict[str, object]) -> int:
        rows = self.read_all(table)
        count = 0
        for row in rows:
            if predicate(row):
                for key, value in changes.items():
                    if key not in self.schemas[table]:
                        raise ValueError(f"Unknown field {key} for table {table}")
                    row[key] = str(value)
                count += 1
        if count:
            self._atomic_write(self.path_for(table), rows, self.schemas[table])
        return count

    def _normalize(self, table: str, row: dict[str, object]) -> dict[str, str]:
        headers = self.schemas[table]
        return {header: str(row.get(header, "")) for header in headers}

    def _atomic_write(self, path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})
        os.replace(temp_path, path)
