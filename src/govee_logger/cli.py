import argparse
import asyncio
import contextlib
import csv
import logging
import os
import re
import signal
import sys
from importlib.metadata import version
from pathlib import Path

from bleak.exc import BleakError

from . import store
from .config import load
from .history import download, supports_history
from .scanner import collect

log = logging.getLogger("govee_logger")

CONNECT_ATTEMPTS = 3


async def _scan(cfg, seconds: float | None, addresses: set[str] | None = None):
    expected = addresses or set(cfg.aliases) or None
    samples = await collect(seconds or cfg.scan_seconds, cfg.adapter, expected)
    for s in samples.values():
        log.info(
            "%s (%s): %.1f°C %.1f%% battery %d%% rssi %d",
            cfg.aliases.get(s.address, s.name), s.address,
            s.reading.temperature, s.reading.humidity, s.reading.battery, s.rssi,
        )
    if missing := (expected or set()) - samples.keys():
        log.warning("not seen: %s", ", ".join(cfg.aliases.get(a, a) for a in sorted(missing)))
    return samples


def cmd_scan(cfg, args) -> int:
    samples = asyncio.run(_scan(cfg, args.seconds))
    if not samples:
        log.error("no Govee devices found")
        return 1
    if not args.dry_run:
        with store.connect(cfg.db_path) as conn:
            store.record_samples(conn, list(samples.values()))
    return 0


async def _download_all(cfg, args) -> int:
    addresses = {a.upper() for a in args.address} or None
    samples = await _scan(cfg, args.seconds, addresses)
    if addresses:
        samples = {a: s for a, s in samples.items() if a in addresses}
    if not samples:
        log.error("no Govee devices found")
        return 1

    conn = store.connect(cfg.db_path)
    store.record_samples(conn, list(samples.values()))
    failed = 0
    for s in samples.values():
        label = cfg.aliases.get(s.address, s.name)
        if not supports_history(s.name):
            log.info("%s: model has no supported history download, skipping", label)
            continue
        since = None if args.full else store.last_download(conn, s.address)
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                dl = await download(s.device, since)
                break
            except (BleakError, TimeoutError, RuntimeError) as e:
                log.warning("%s: attempt %d/%d failed: %s", label, attempt, CONNECT_ATTEMPTS, e or type(e).__name__)
        else:
            failed += 1
            continue
        store.record_download(conn, s.address, dl)
        log.info("%s: %d records%s", label, len(dl.records), "" if dl.complete else " (incomplete, will retry next run)")
    conn.close()
    return 1 if failed else 0


def cmd_download(cfg, args) -> int:
    return asyncio.run(_download_all(cfg, args))


INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def interval(value: str) -> str:
    if not re.fullmatch(r"\d+[smhd]", value):
        raise argparse.ArgumentTypeError(f"expected e.g. 30m, 6h or 1d, got {value!r}")
    return value


def interval_seconds(value: str) -> int:
    return int(value[:-1]) * INTERVAL_UNITS[value[-1]]


async def _run_forever(cfg, args) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    stopping = asyncio.create_task(stop.wait())

    while True:
        # An interrupted transfer is safe: the download watermark only advances on completion.
        downloading = asyncio.create_task(_download_all(cfg, args))
        await asyncio.wait({downloading, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            downloading.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await downloading
            return 0
        try:
            downloading.result()
        except Exception:
            log.exception("download failed, retrying next run")

        log.info("next run in %s", args.every)
        await asyncio.wait({stopping}, timeout=interval_seconds(args.every))
        if stop.is_set():
            return 0


def cmd_run(cfg, args) -> int:
    return asyncio.run(_run_forever(cfg, args))


def cmd_latest(cfg, args) -> int:
    with store.connect(cfg.db_path) as conn:
        rows = store.latest(conn)
    for r in rows:
        label = cfg.aliases.get(r["address"], r["name"])
        print(
            f"{r['ts']}  {label:<20} {r['temperature']:6.1f}°C {r['humidity']:5.1f}%  "
            f"bat {r['battery']}%  downloaded {r['last_download'] or 'never'}"
        )
    return 0


def cmd_export(cfg, args) -> int:
    with store.connect(cfg.db_path) as conn:
        rows = store.history(conn, args.since)
    writer = csv.writer(sys.stdout)
    writer.writerow(["ts", "address", "label", "temperature", "humidity"])
    for r in rows:
        label = cfg.aliases.get(r["address"], r["name"])
        writer.writerow([r["ts"], r["address"], label, r["temperature"], r["humidity"]])
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="govee-logger")
    parser.add_argument("--version", action="version", version=version("govee-logger"))
    parser.add_argument(
        "--config", type=Path, default=os.environ.get("GOVEE_LOGGER_CONFIG"),
        help="path to config.toml (env GOVEE_LOGGER_CONFIG, default /etc/govee-logger/config.toml)",
    )
    parser.add_argument(
        "--db", type=Path, default=os.environ.get("GOVEE_LOGGER_DB"),
        help="database path (env GOVEE_LOGGER_DB, overrides the config file)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="record the current reading from each device's broadcast")
    p.add_argument("--seconds", type=float, help="scan duration")
    p.add_argument("--dry-run", action="store_true", help="print readings without saving")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("download", help="connect to each device and pull its stored per-minute history")
    p.add_argument("--seconds", type=float, help="scan duration used to find devices")
    p.add_argument("--address", action="append", default=[], help="only this device (repeatable)")
    p.add_argument("--full", action="store_true", help="fetch everything stored (~20 days), not just what is new")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("run", help="download now, then again at a fixed interval until stopped")
    p.add_argument("--every", type=interval, default="24h", help="interval, e.g. 6h or 1d (default 24h)")
    p.add_argument("--seconds", type=float, help="scan duration used to find devices")
    p.add_argument("--address", action="append", default=[], help="only this device (repeatable)")
    p.set_defaults(func=cmd_run, full=False)

    p = sub.add_parser("latest", help="show the most recent reading per device")
    p.set_defaults(func=cmd_latest)

    p = sub.add_parser("export", help="dump readings as CSV")
    p.add_argument("--since", help="ISO timestamp lower bound, e.g. 2026-09-01")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load(args.config)
    if args.db:
        cfg.db_path = args.db
    try:
        sys.exit(args.func(cfg, args))
    except (BleakError, OSError) as e:
        log.error("%s", e)
        sys.exit(1)
