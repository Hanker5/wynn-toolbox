"""Bit streams in WynnBuilder's link format.

Links use a custom Base64 alphabet. Each character holds 6 bits, least-significant
bit first, and multi-bit fields are also written LSB-first.
"""
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+-"
_VALUE = {c: i for i, c in enumerate(ALPHABET)}


class BitWriter:
    def __init__(self):
        self.bits = []

    def write(self, value, width):
        if value < 0 or value >= 1 << width:
            raise ValueError(f"{value} does not fit in {width} bits")
        self.bits.extend((value >> j) & 1 for j in range(width))

    def flag(self, spec, name):
        """Write a named flag from an encoding-constants entry like {"NO": 0, "BITLEN": 1}."""
        self.write(spec[name], spec["BITLEN"])

    def to_b64(self):
        bits = self.bits + [0] * (-len(self.bits) % 6)
        return "".join(ALPHABET[sum(bits[k + j] << j for j in range(6))]
                       for k in range(0, len(bits), 6))


class BitReader:
    def __init__(self, text):
        self.bits = [(_VALUE[c] >> j) & 1 for c in text for j in range(6)]
        self.pos = 0

    def read(self, width):
        if self.pos + width > len(self.bits):
            raise ValueError("link ended unexpectedly")
        v = sum(self.bits[self.pos + j] << j for j in range(width))
        self.pos += width
        return v

    def read_flag(self, spec):
        return self.read(spec["BITLEN"])

    def remaining(self):
        return len(self.bits) - self.pos


def is_binary_link(text):
    """WynnBuilder's current format starts with a character worth more than 11."""
    return _VALUE[text[0]] > 11
