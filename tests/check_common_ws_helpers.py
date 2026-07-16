"""Check websocket helpers after extracting them from common.py."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
from common_ws import ws_accept_key, ws_recv, ws_send  # noqa: E402


class CaptureSocket:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()

    def recv(self, n):
        chunk = self.incoming[:n]
        del self.incoming[:n]
        return bytes(chunk)

    def sendall(self, data):
        self.sent += data


class SlottedSocket:
    __slots__ = ("sent",)

    def __init__(self):
        self.sent = bytearray()

    def sendall(self, data):
        self.sent += data


def _masked_frame(opcode, payload, mask=b"\x01\x02\x03\x04"):
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + bytes(
        payload[i] ^ mask[i % 4] for i in range(len(payload))
    )


def main():
    assert ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    assert common.ws_accept_key is ws_accept_key
    assert common.ws_recv is ws_recv
    assert common.ws_send is ws_send

    out = CaptureSocket()
    ws_send(out, b"hi", opcode=0x1)
    assert bytes(out.sent) == b"\x81\x02hi"

    slotted = SlottedSocket()
    ws_send(slotted, b"ok", opcode=0x1)
    assert bytes(slotted.sent) == b"\x81\x02ok"

    inc = CaptureSocket(_masked_frame(0x1, b"hi"))
    op, payload = ws_recv(inc)
    assert op == 0x1
    assert payload == b"hi"

    print("common websocket helper checks passed")


if __name__ == "__main__":
    main()
