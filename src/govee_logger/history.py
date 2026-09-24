import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bleak import BleakClient
from bleak.backends.device import BLEDevice

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
    until: datetime


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


async def download(device: BLEDevice | str, since: datetime | None, idle_timeout: float = 15) -> Download:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start, end = minutes_to_fetch(now, since), 1
    by_offset: dict[int, tuple[float, float]] = {}
    packets = 0
    reported_packets: int | None = None
    keep_alive_due = False
    activity = asyncio.Event()
    key: bytes | None = None

    def on_data(_, data: bytearray):
        nonlocal packets, keep_alive_due
        data = decrypt(key, bytes(data))
        packets += 1
        for offset, temperature, humidity in parse_packet(data):
            by_offset[offset] = (temperature, humidity)
        if packets % (KEEP_ALIVE_EVERY // 6) == 0:
            keep_alive_due = True
        activity.set()

    def on_command(_, data: bytearray):
        nonlocal reported_packets
        data = decrypt(key, bytes(data))
        if data[:2] == TRANSFER_DONE:
            reported_packets = int.from_bytes(data[2:4], "big")
            activity.set()

    log.info("requesting %d minutes of history", start)
    async with BleakClient(device, timeout=30) as client:
        key = await _handshake(client)
        await client.start_notify(DATA_UUID, on_data)
        await client.start_notify(COMMAND_UUID, on_command)
        await client.write_gatt_char(COMMAND_UUID, encrypt(key, build_request(start, end)), response=True)
        while reported_packets is None:
            activity.clear()
            try:
                await asyncio.wait_for(activity.wait(), idle_timeout)
            except TimeoutError:
                log.warning("transfer stalled after %d packets", packets)
                break
            if keep_alive_due:
                keep_alive_due = False
                await client.write_gatt_char(COMMAND_UUID, encrypt(key, frame(KEEP_ALIVE)), response=True)

    complete = reported_packets is not None and reported_packets == packets
    if reported_packets is not None and not complete:
        log.warning("device reported %d packets, received %d", reported_packets, packets)
    records = [
        HistoryRecord(now - timedelta(minutes=offset), t, h) for offset, (t, h) in sorted(by_offset.items(), reverse=True)
    ]
    return Download(records, complete, now - timedelta(minutes=end))
