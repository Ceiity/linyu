"""Minimal RFB (VNC) client used to show SnowLuma's QQ login window.

SnowLuma only supports QR login inside the real Linux QQ window, which its
official image renders on Xvfb and exposes through x11vnc (port 5900, VNC
password authentication).  Instead of asking the user to open noVNC, the panel
connects to that same x11vnc server, grabs one frame, crops it to the QQ
window and shows it in the unified login page.  Clicks on the image are sent
back as ordinary pointer events (e.g. to refresh an expired code inside QQ).

Nothing here bypasses QQ: the user still scans and confirms in mobile QQ.

Implements RFB 3.3 / 3.7 / 3.8, security types None(1) and VNC Auth(2),
32bpp true-colour Raw encoding only.
"""
from __future__ import annotations

import base64
import hashlib
import io
import socket
import struct


class RFBError(Exception):
    pass


def _reverse_bits(b: int) -> int:
    return int("{:08b}".format(b)[::-1], 2)


def vnc_des_response(password: str, challenge: bytes) -> bytes:
    """VNC auth: DES-encrypt the 16-byte challenge with the bit-reversed password."""
    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    except Exception:  # cryptography < 43
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES  # type: ignore
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    key = (password.encode("latin-1", errors="ignore") + b"\0" * 8)[:8]
    key = bytes(_reverse_bits(b) for b in key)
    # A 64-bit TripleDES key degrades to single DES (K1 == K2 == K3), which is what VNC uses.
    enc = Cipher(TripleDES(key), modes.ECB()).encryptor()
    return enc.update(challenge) + enc.finalize()


class RFBClient:
    def __init__(self, host: str, port: int, password: str = "", timeout: float = 8.0):
        self.host = host
        self.port = int(port)
        self.password = password or ""
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.width = 0
        self.height = 0
        self.name = ""

    # -- low level -----------------------------------------------------
    def _recv(self, n: int) -> bytes:
        assert self.sock is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            if not chunk:
                raise RFBError("VNC 连接被关闭")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_into(self, view: memoryview) -> None:
        assert self.sock is not None
        got = 0
        total = len(view)
        while got < total:
            n = self.sock.recv_into(view[got:], min(total - got, 1 << 20))
            if not n:
                raise RFBError("VNC 连接被关闭")
            got += n

    def _send(self, data: bytes) -> None:
        assert self.sock is not None
        self.sock.sendall(data)

    # -- handshake -----------------------------------------------------
    def connect(self) -> "RFBClient":
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise RFBError("连不上远程桌面 %s:%s（%s）" % (self.host, self.port, e)) from e
        self.sock.settimeout(self.timeout)
        banner = self._recv(12)
        if not banner.startswith(b"RFB "):
            raise RFBError("不是 VNC 服务")
        try:
            major, minor = int(banner[4:7]), int(banner[8:11])
        except ValueError as e:
            raise RFBError("VNC 版本无法识别") from e
        if major != 3:
            raise RFBError("VNC 版本不支持：%r" % banner)
        minor = 8 if minor >= 8 else (7 if minor >= 7 else 3)
        self._send(b"RFB 003.%03d\n" % minor)
        if minor == 3:
            (sec,) = struct.unpack(">I", self._recv(4))
            if sec == 0:
                self._fail_reason()
            types = [sec]
        else:
            (count,) = struct.unpack(">B", self._recv(1))
            if count == 0:
                self._fail_reason()
            types = list(self._recv(count))
        if 2 in types and (self.password or 1 not in types):
            chosen = 2
        elif 1 in types:
            chosen = 1
        else:
            raise RFBError("VNC 安全类型不支持：%s" % types)
        if minor != 3:
            self._send(struct.pack(">B", chosen))
        if chosen == 2:
            if not self.password:
                raise RFBError("远程桌面需要密码，但没有读取到 SnowLuma 的远程桌面密码")
            challenge = self._recv(16)
            self._send(vnc_des_response(self.password, challenge))
        if chosen == 2 or minor == 8:
            (result,) = struct.unpack(">I", self._recv(4))
            if result != 0:
                if minor == 8:
                    self._fail_reason()
                raise RFBError("远程桌面密码错误")
        self._send(b"\x01")  # ClientInit: shared session, do not kick noVNC viewers
        head = self._recv(24)
        self.width, self.height = struct.unpack(">HH", head[:4])
        (name_len,) = struct.unpack(">I", head[20:24])
        self.name = self._recv(name_len).decode("utf-8", errors="replace") if name_len else ""
        # 32bpp, depth 24, little endian, true colour, 8 bits per channel, R<<16 G<<8 B.
        pixel_format = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self._send(b"\x00\x00\x00\x00" + pixel_format)
        self._send(struct.pack(">BxHi", 2, 1, 0))  # SetEncodings: Raw only
        return self

    def _fail_reason(self) -> None:
        try:
            (n,) = struct.unpack(">I", self._recv(4))
            reason = self._recv(min(n, 4096)).decode("utf-8", errors="replace")
        except Exception:
            reason = ""
        raise RFBError("VNC 拒绝连接：%s" % (reason or "未知原因"))

    # -- operations ----------------------------------------------------
    def framebuffer(self) -> bytes:
        """Return the whole screen as BGRX bytes (width*height*4)."""
        w, h = self.width, self.height
        if not w or not h:
            raise RFBError("远程桌面尺寸为 0")
        fb = bytearray(w * h * 4)
        self._send(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))
        while True:
            (msg_type,) = struct.unpack(">B", self._recv(1))
            if msg_type == 0:  # FramebufferUpdate
                _, nrects = struct.unpack(">BH", self._recv(3))
                for _ in range(nrects):
                    x, y, rw, rh, enc = struct.unpack(">HHHHi", self._recv(12))
                    if enc != 0:
                        raise RFBError("VNC 返回了未请求的编码 %d" % enc)
                    if rw == 0 or rh == 0:
                        continue
                    row_bytes = rw * 4
                    data = bytearray(row_bytes * rh)
                    self._recv_into(memoryview(data))
                    if x == 0 and rw == w:
                        start = y * w * 4
                        fb[start:start + len(data)] = data
                    else:
                        for r in range(rh):
                            dst = ((y + r) * w + x) * 4
                            fb[dst:dst + row_bytes] = data[r * row_bytes:(r + 1) * row_bytes]
                return bytes(fb)
            if msg_type == 1:  # SetColourMapEntries
                _, _first, n = struct.unpack(">BHH", self._recv(5))
                self._recv(n * 6)
            elif msg_type == 2:  # Bell
                continue
            elif msg_type == 3:  # ServerCutText
                self._recv(3)
                (n,) = struct.unpack(">I", self._recv(4))
                self._recv(n)
            else:
                raise RFBError("VNC 消息类型未知：%d" % msg_type)

    def click(self, x: int, y: int, button: int = 1) -> None:
        x = max(0, min(int(x), max(0, self.width - 1)))
        y = max(0, min(int(y), max(0, self.height - 1)))
        self._send(struct.pack(">BBHH", 5, 0, x, y))
        self._send(struct.pack(">BBHH", 5, button & 0xFF, x, y))
        self._send(struct.pack(">BBHH", 5, 0, x, y))

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()


def content_box(img, threshold: int = 28, bar_ratio: float = 0.85, pad: int = 14):
    """Bounding box of everything that is not desktop background.

    Full-width rows / full-height columns (window-manager toolbars) are ignored
    so the box tightens around the QQ window.  Returns None for a blank screen.
    """
    from PIL import Image, ImageChops

    w, h = img.size
    small = img.resize((max(1, w // 4), max(1, h // 4)), Image.NEAREST)
    colors = small.getcolors(small.size[0] * small.size[1]) or []
    if not colors:
        return None
    bg = max(colors, key=lambda c: c[0])[1]
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg)).convert("L")
    mask = diff.point(lambda v: 255 if v > threshold else 0)
    rows = list(mask.resize((1, h), Image.BOX).getdata())
    cols = list(mask.resize((w, 1), Image.BOX).getdata())
    bar_level = 255 * bar_ratio
    ys = [i for i, v in enumerate(rows) if 2 < v < bar_level]
    xs = [i for i, v in enumerate(cols) if 2 < v < bar_level]
    if not ys or not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    if (x1 - x0) < 40 or (y1 - y0) < 40:
        return None
    return (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def capture(host: str, port: int, password: str, crop: bool = True, max_width: int = 960, timeout: float = 8.0) -> dict:
    """Grab one frame and return a PNG (base64) plus the geometry needed to map clicks back."""
    from PIL import Image

    with RFBClient(host, port, password, timeout=timeout) as cli:
        raw = cli.framebuffer()
        width, height = cli.width, cli.height
    img = Image.frombuffer("RGB", (width, height), raw, "raw", "BGRX", 0, 1)
    box = content_box(img) if crop else None
    blank = box is None and crop
    if box:
        img = img.crop(box)
    else:
        box = (0, 0, width, height)
    scale = 1.0
    if img.size[0] > max_width:
        scale = max_width / float(img.size[0])
        img = img.resize((max_width, max(1, int(img.size[1] * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    return {
        "png_base64": base64.b64encode(png).decode("ascii"),
        "sha": hashlib.sha256(png).hexdigest(),
        "screen": {"width": width, "height": height},
        "box": list(box),
        "scale": scale,
        "image": {"width": img.size[0], "height": img.size[1]},
        "blank": blank,
    }


def map_click(x: float, y: float, geometry: dict) -> tuple[int, int]:
    """Map a click on the displayed (cropped, scaled) image back to screen coordinates."""
    box = geometry.get("box") or [0, 0, 0, 0]
    scale = float(geometry.get("scale") or 1.0) or 1.0
    sx = int(box[0] + float(x) / scale)
    sy = int(box[1] + float(y) / scale)
    sx = max(int(box[0]), min(sx, int(box[2]) - 1))
    sy = max(int(box[1]), min(sy, int(box[3]) - 1))
    return sx, sy


def click(host: str, port: int, password: str, x: int, y: int, timeout: float = 6.0) -> None:
    with RFBClient(host, port, password, timeout=timeout) as cli:
        cli.click(x, y)
