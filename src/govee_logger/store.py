import sqlite3
from datetime import datetime
from pathlib import Path

from .history import Download
from .scanner import Sample

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    address     TEXT NOT NULL,
    ts          TEXT NOT NULL,
    temperature REAL NOT NULL,
    humidity    REAL NOT NULL,
    PRIMARY KEY (address, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS devices (
    address       TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    battery       INTEGER,
    rssi          INTEGER,
    last_seen     TEXT,
    last_download TEXT
);
"""


def _ts(dt: datetime) -> str:
    return dt.replace(second=0, microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def record_samples(conn: sqlite3.Connection, samples: list[Sample]) -> None:
    with conn:
        conn.executemany(
            """
            INSERT INTO devices (address, name, battery, rssi, last_seen) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (address) DO UPDATE SET
                name = excluded.name, battery = excluded.battery, rssi = excluded.rssi, last_seen = excluded.last_seen
            """,
            [(s.address, s.name, s.reading.battery, s.rssi, s.timestamp.isoformat(timespec="seconds")) for s in samples],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO readings VALUES (?, ?, ?, ?)",
            [(s.address, _ts(s.timestamp), s.reading.temperature, s.reading.humidity) for s in samples],
        )


def record_download(conn: sqlite3.Connection, address: str, dl: Download) -> None:
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO readings VALUES (?, ?, ?, ?)",
            [(address, _ts(r.timestamp), r.temperature, r.humidity) for r in dl.records],
        )
        # Only advance the watermark on a complete transfer, so an interrupted one is retried next run.
        if dl.complete:
            conn.execute("UPDATE devices SET last_download = ? WHERE address = ?", (_ts(dl.until), address))


def last_download(conn: sqlite3.Connection, address: str) -> datetime | None:
    row = conn.execute("SELECT last_download FROM devices WHERE address = ?", (address,)).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def latest(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT d.address, d.name, d.battery, d.last_download, r.ts, r.temperature, r.humidity
        FROM devices d
        JOIN readings r ON r.address = d.address
        WHERE r.ts = (SELECT MAX(ts) FROM readings WHERE address = d.address)
        ORDER BY d.address
        """
    ).fetchall()


def history(conn: sqlite3.Connection, since: str | None) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT r.ts, r.address, d.name, r.temperature, r.humidity
        FROM readings r LEFT JOIN devices d ON d.address = r.address
        WHERE r.ts >= ? ORDER BY r.ts, r.address
        """,
        (since or "",),
    ).fetchall()
