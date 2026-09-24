import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .decode import Reading, decode


@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    address: str
    name: str
    rssi: int
    reading: Reading
    device: BLEDevice = field(compare=False, repr=False)


async def collect(duration: float, adapter: str | None = None, expected: set[str] | None = None) -> dict[str, Sample]:
    """Listen for advertisements and keep the latest reading per device.

    Returns early once every address in `expected` has been seen.
    """
    samples: dict[str, Sample] = {}
    names: dict[str, str] = {}
    done = asyncio.Event()

    def on_advertisement(device, adv):
        address = device.address.upper()
        name = adv.local_name or device.name or names.get(address, "")
        if name:
            names[address] = name
        reading = decode(name, adv.manufacturer_data)
        if reading is None:
            return
        samples[address] = Sample(datetime.now(timezone.utc), address, name, adv.rssi, reading, device)
        if expected and expected <= samples.keys():
            done.set()

    kwargs = {"adapter": adapter} if adapter else {}
    async with BleakScanner(on_advertisement, **kwargs):
        try:
            await asyncio.wait_for(done.wait(), timeout=duration)
        except TimeoutError:
            pass
    return samples
