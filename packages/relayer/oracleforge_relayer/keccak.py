"""Pure-Python Keccak-256 (Ethereum variant).

The stdlib's ``hashlib.sha3_256`` is NIST SHA3 (0x06 domain padding), which is
*not* the keccak256 Ethereum uses (0x01 padding). The relayer must compute the
same ``questionHash`` / ``marketId`` the Solidity ``MarketEngine`` does, so we
implement keccak256 here with no third-party dependency. Verified against known
vectors in the tests.
"""
from __future__ import annotations

_MASK = 0xFFFFFFFFFFFFFFFF

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

# rotation offsets r[x][y]
_R = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(A):
    for rc in _RC:
        # theta
        C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
        D = [C[(x + 4) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                A[x][y] ^= D[x]
        # rho + pi
        B = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _R[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                A[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y])
        # iota
        A[0][0] ^= rc
    return A


def keccak256(msg: bytes) -> bytes:
    rate = 136  # bytes (1088-bit rate, 512-bit capacity)
    m = bytearray(msg)
    m.append(0x01)  # keccak domain padding (SHA3 would be 0x06)
    while len(m) % rate != 0:
        m.append(0x00)
    m[-1] ^= 0x80

    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(m), rate):
        block = m[off:off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:i * 8 + 8], "little")
            A[i % 5][i // 5] ^= lane
        _keccak_f(A)

    out = bytearray()
    for i in range(rate // 8):
        out += A[i % 5][i // 5].to_bytes(8, "little")
        if len(out) >= 32:
            break
    return bytes(out[:32])


def keccak256_hex(msg: bytes) -> str:
    return "0x" + keccak256(msg).hex()
