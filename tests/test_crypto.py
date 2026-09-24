from govee_logger.crypto import PRE_SHARED_KEY, decrypt, encrypt, frame


def test_frame_checksum():
    assert frame(b"\xaa\x01") == bytes.fromhex("aa01" + "00" * 17 + "ab")


def test_round_trip():
    packet = frame(b"\xe7\x01")
    ciphertext = encrypt(PRE_SHARED_KEY, packet)
    assert ciphertext != packet
    assert decrypt(PRE_SHARED_KEY, ciphertext) == packet


def test_no_key_is_plaintext():
    assert encrypt(None, b"x" * 20) == b"x" * 20
