# -*- coding: utf-8 -*-
"""Minimal RFC 6455 websocket frame helpers used by manager/native sessions."""
import base64
import hashlib
import os

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise OSError("socket closed")
        data += chunk
    return bytes(data)


def ws_recv(sock):
    """Read one ws message; transparently answers ping. Returns (opcode, payload) or (None,None)."""
    while True:
        hdr = _recv_exact(sock, 2)
        b1, b2 = hdr[0], hdr[1]
        op = b1 & 0x0f
        masked = b2 & 0x80
        length = b2 & 0x7f
        if length == 126:
            length = int.from_bytes(_recv_exact(sock, 2), "big")
        elif length == 127:
            length = int.from_bytes(_recv_exact(sock, 8), "big")
        mask = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, length) if length else b""
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        if op == 0x9:  # ping -> pong
            ws_send(sock, payload, 0xA)
            continue
        if op == 0xA:  # pong
            continue
        return op, payload


def ws_send(sock, payload, opcode=0x2, mask=False):
    out = bytearray([0x80 | opcode])
    length = len(payload)
    mflag = 0x80 if mask else 0x00
    if length < 126:
        out.append(mflag | length)
    elif length < 65536:
        out.append(mflag | 126)
        out += length.to_bytes(2, "big")
    else:
        out.append(mflag | 127)
        out += length.to_bytes(8, "big")
    if mask:
        m = os.urandom(4)
        out += m
        payload = bytes(payload[i] ^ m[i % 4] for i in range(len(payload)))
    out += payload
    sock.sendall(bytes(out))


def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
