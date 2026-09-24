"""Packet encryption used by newer Govee firmware.

Each 20-byte packet is AES-128-ECB on the first 16 bytes and RC4 on the last 4.
The handshake is encrypted with a pre-shared key hardcoded in the Govee Home app;
the device then hands out a per-connection session key.
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PRE_SHARED_KEY = b"MakingLifeSmarte"


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def encrypt(key: bytes | None, packet: bytes) -> bytes:
    if key is None:
        return packet
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(packet[:16]) + enc.finalize() + _rc4(key, packet[16:])


def decrypt(key: bytes | None, packet: bytes) -> bytes:
    if key is None:
        return packet
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(packet[:16]) + dec.finalize() + _rc4(key, packet[16:])


def frame(payload: bytes) -> bytes:
    """Pad a command to 20 bytes with a trailing XOR checksum."""
    body = payload.ljust(19, b"\x00")
    checksum = 0
    for b in body:
        checksum ^= b
    return body + bytes([checksum])
