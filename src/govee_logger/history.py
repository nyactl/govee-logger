import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bleak import BleakClient
from bleak.exc import BleakError

from .crypto import PRE_SHARED_KEY, decrypt, encrypt, frame
from .decode import unpack_packed

UUID_PREFIX = "494e5445-4c4c-495f-524f-434b535f"
DEVICE_UUID = UUID_PREFIX + "2011"
COMMAND_UUID = UUID_PREFIX + "2012"
DATA_UUID = UUID_PREFIX + "2013"
AUTH_NOTIFY_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"
AUTH_WRITE_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

REQUEST_RECORDS = b"\x33\x01"
KEEP_ALIVE = b"\xaa\x01"
TRANSFER_DONE = b"\xee\x01"
# The device stalls unless it gets a keep-alive roughly every 450 records.
KEEP_ALIVE_EVERY = 450

MAX_MINUTES = 20 * 24 * 60
SUPPORTED_MODELS = ("H5072", "H5075", "H5100", "H5101", "H5102", "H5104", "H5174", "H5177")
EMPTY_RECORD = b"\xff\xff\xff"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoryRecord:
    timestamp: datetime
    temperature: float
    humidity: float


@dataclass(frozen=True)
class Download:
    records: list[HistoryRecord]
    complete: bool
    # Newest minute up to which nothing is missing; None if not even the oldest minute arrived.
    until: datetime | None


def supports_history(name: str) -> bool:
    return any(model in name for model in SUPPORTED_MODELS)


def build_request(start: int, end: int) -> bytes:
    """Request records from `start` down to `end` minutes ago."""
    return frame(REQUEST_RECORDS + start.to_bytes(2, "big") + end.to_bytes(2, "big"))


def parse_packet(data: bytes) -> list[tuple[int, float, float]]:
    """A packet holds up to 6 one-minute records, starting `offset` minutes ago and counting down."""
    offset = int.from_bytes(data[0:2], "big")
    records = []
    for i in range(6):
        chunk = data[2 + 3 * i : 5 + 3 * i]
        if len(chunk) < 3 or chunk == EMPTY_RECORD or offset - i < 1:
            continue
        records.append((offset - i, *unpack_packed(chunk)))
    return records


def minutes_to_fetch(now: datetime, since: datetime | None) -> int:
    if since is None:
        return MAX_MINUTES
    return max(1, min(MAX_MINUTES, int((now - since).total_seconds() // 60)))


async def _handshake(client: BleakClient) -> bytes | None:
    """Negotiate a session key on firmware that requires it; returns None for plaintext devices."""
    if client.services.get_characteristic(AUTH_WRITE_UUID) is None:
        return None
    replies: asyncio.Queue[bytes] = asyncio.Queue()
    await client.start_notify(AUTH_NOTIFY_UUID, lambda _, d: replies.put_nowait(decrypt(PRE_SHARED_KEY, bytes(d))))
    await client.write_gatt_char(AUTH_WRITE_UUID, encrypt(PRE_SHARED_KEY, frame(b"\xe7\x01")), response=True)
    rx1 = await asyncio.wait_for(replies.get(), 10)
    if rx1[:2] != b"\xe7\x01":
        raise RuntimeError(f"unexpected handshake reply {rx1.hex()}")
    await client.write_gatt_char(AUTH_WRITE_UUID, encrypt(PRE_SHARED_KEY, frame(b"\xe7\x02")), response=True)
    await asyncio.wait_for(replies.get(), 10)
    return rx1[2:18]


def _missing_span(wanted: list[datetime], covered: set[datetime]) -> tuple[datetime, datetime] | None:
    missing = [m for m in wanted if m not in covered]
    return (missing[0], missing[-1]) if missing else None


def _watermark(wanted: list[datetime], covered: set[datetime]) -> datetime | None:
    """Newest minute up to which every wanted minute has arrived."""
    newest = None
    for minute in wanted:
        if minute not in covered:
            break
        newest = minute
    return newest


def _minute_now() -> datetime:
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


async def _transfer(
    client: BleakClient,
    key: bytes | None,
    span: tuple[datetime, datetime],
    covered: set[datetime],
    readings: dict[datetime, tuple[float, float]],
    idle_timeout: float,
) -> bool:
    """Request one span; returns False if the device went quiet before finishing."""
    now = _minute_now()
    start = max(1, int((now - span[0]).total_seconds() // 60))
    end = max(1, int((now - span[1]).total_seconds() // 60))
    packets = 0
    finished = False
    keep_alive_due = False
    activity = asyncio.Event()

    def on_data(_, data: bytearray):
        nonlocal packets, keep_alive_due
        data = decrypt(key, bytes(data))
        packets += 1
        # A packet covers 6 minutes even where they hold no reading (before the device had data).
        header = int.from_bytes(data[0:2], "big")
        for offset in range(max(header - 5, end), header + 1):
            covered.add(now - timedelta(minutes=offset))
        for offset, temperature, humidity in parse_packet(data):
            readings[now - timedelta(minutes=offset)] = (temperature, humidity)
        if packets % (KEEP_ALIVE_EVERY // 6) == 0:
            keep_alive_due = True
        activity.set()

    def on_command(_, data: bytearray):
        nonlocal finished
        if decrypt(key, bytes(data))[:2] == TRANSFER_DONE:
            finished = True
            activity.set()

    log.info("requesting %d minutes of history", start - end + 1)
    await client.start_notify(DATA_UUID, on_data)
    await client.start_notify(COMMAND_UUID, on_command)
    try:
        await client.write_gatt_char(COMMAND_UUID, encrypt(key, build_request(start, end)), response=True)
        while not finished:
            activity.clear()
            try:
                await asyncio.wait_for(activity.wait(), idle_timeout)
            except TimeoutError:
                log.warning("transfer stalled after %d packets", packets)
                return False
            if keep_alive_due:
                keep_alive_due = False
                await client.write_gatt_char(COMMAND_UUID, encrypt(key, frame(KEEP_ALIVE)), response=True)
        return True
    finally:
        # The link may already be gone; the caller handles that from the original error.
        with contextlib.suppress(BleakError):
            await client.stop_notify(DATA_UUID)
            await client.stop_notify(COMMAND_UUID)


async def download(
    address: str,
    since: datetime | None,
    have: set[datetime] = frozenset(),
    connections: int = 3,
    passes: int = 20,
    idle_timeout: float = 15,
) -> Download:
    """Fetch every minute after `since` not already in `have`, re-requesting whatever a weak link dropped.

    Connects by address rather than a scanned BLEDevice: BlueZ drops unconnected devices
    from its cache ~30s after discovery stops, and bleak rescans for an address.
    """
    now = _minute_now()
    wanted = [now - timedelta(minutes=m) for m in range(minutes_to_fetch(now, since), 0, -1)]
    covered: set[datetime] = set(have)
    readings: dict[datetime, tuple[float, float]] = {}
    remaining_passes = passes

    for attempt in range(1, connections + 1):
        if _missing_span(wanted, covered) is None or remaining_passes == 0:
            break
        try:
            async with BleakClient(address, timeout=30) as client:
                key = await _handshake(client)
                while remaining_passes and (span := _missing_span(wanted, covered)):
                    remaining_passes -= 1
                    before = len(covered)
                    if not await _transfer(client, key, span, covered, readings, idle_timeout) and len(covered) == before:
                        break
        except (BleakError, TimeoutError, RuntimeError) as e:
            log.warning("connection %d/%d failed: %s", attempt, connections, str(e) or type(e).__name__)

    complete = _missing_span(wanted, covered) is None
    if not complete:
        log.warning("%d of %d minutes still missing", sum(m not in covered for m in wanted), len(wanted))
    records = [HistoryRecord(ts, t, h) for ts, (t, h) in sorted(readings.items())]
    return Download(records, complete, _watermark(wanted, covered))
