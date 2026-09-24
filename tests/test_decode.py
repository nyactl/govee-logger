from govee_logger.decode import MFR_H507X, MFR_H510X, MFR_H5179, Reading, decode


def test_h5075():
    data = bytes.fromhex("00037f7a6400")
    assert decode("GVH5075_ABCD", {MFR_H507X: data}) == Reading(22.9, 24.2, 100)


def test_h5075_negative_temperature():
    data = bytes([0x00]) + (0x800000 | 53456).to_bytes(3, "big") + bytes([0x50, 0x00])
    assert decode("GVH5075_ABCD", {MFR_H507X: data}) == Reading(-5.3, 45.6, 80)


def test_h5074():
    data = bytes([0x00]) + (2345).to_bytes(2, "little") + (5678).to_bytes(2, "little") + bytes([0x55, 0x02])
    assert decode("Govee_H5074_ABCD", {MFR_H507X: data}) == Reading(23.45, 56.78, 85)


def test_h5179():
    data = bytes.fromhex("01000101") + (-150).to_bytes(2, "little", signed=True) + (4000).to_bytes(2, "little") + bytes([0x40])
    assert decode("Govee_H5179_ABCD", {MFR_H5179: data}) == Reading(-1.5, 40.0, 64)


def test_h5102():
    data = bytes.fromhex("0101037f7a64")
    assert decode("GVH5102_ABCD", {MFR_H510X: data}) == Reading(22.9, 24.2, 100)


def test_h510x_requires_govee_name():
    assert decode("SomeOtherDevice", {MFR_H510X: bytes.fromhex("0101037f7a64")}) is None


def test_unrelated_data():
    assert decode("", {0x004C: bytes(10)}) is None
