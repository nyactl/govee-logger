from dataclasses import dataclass

MFR_H507X = 0xEC88
MFR_H5179 = 0x8801
MFR_H510X = 0x0001


@dataclass(frozen=True)
class Reading:
    temperature: float
    humidity: float
    battery: int


def unpack_packed(b: bytes) -> tuple[float, float]:
    # Temperature and humidity share one 24-bit integer: TTTHHH (tenths), MSB is the sign bit.
    raw = int.from_bytes(b, "big")
    negative = raw & 0x800000
    raw &= 0x7FFFFF
    temperature = (raw // 1000) / 10
    humidity = (raw % 1000) / 10
    return (-temperature if negative else temperature), humidity


def _unpack_le(b: bytes) -> tuple[float, float, int]:
    temperature = int.from_bytes(b[0:2], "little", signed=True) / 100
    humidity = int.from_bytes(b[2:4], "little") / 100
    return temperature, humidity, b[4]


def is_govee_name(name: str) -> bool:
    return name.startswith(("GVH", "Govee_", "GV5"))


def decode(name: str, manufacturer_data: dict[int, bytes]) -> Reading | None:
    if (data := manufacturer_data.get(MFR_H507X)) is not None:
        if len(data) == 6:  # H5072, H5075
            t, h = unpack_packed(data[1:4])
            return Reading(t, h, data[4])
        if len(data) == 7:  # H5074
            return Reading(*_unpack_le(data[1:6]))

    if (data := manufacturer_data.get(MFR_H5179)) is not None and len(data) == 9:
        return Reading(*_unpack_le(data[4:9]))

    # 0x0001 is not a Govee-registered ID, so require a Govee name to avoid false matches.
    if (data := manufacturer_data.get(MFR_H510X)) is not None and len(data) == 6 and is_govee_name(name):
        t, h = unpack_packed(data[2:5])  # H5100, H5101, H5102, H5104, H5174, H5177
        return Reading(t, h, data[5])

    return None
