"""服务器性能采样：CPU、内存、磁盘、网络速率（读取宿主 /proc，Agent 使用 host 网络）。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

_SKIP_IFACES = ("lo", "docker", "veth", "br-", "virbr", "cni", "flannel", "tun", "tailscale")


def _cpu_times() -> tuple[int, int]:
    parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def _net_bytes() -> tuple[int, int]:
    rx = tx = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, data = line.split(":", 1)
        name = name.strip()
        if name.startswith(_SKIP_IFACES):
            continue
        cols = data.split()
        rx += int(cols[0])
        tx += int(cols[8])
    return rx, tx


def _meminfo() -> dict:
    out = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        out[k] = int(v.split()[0]) * 1024
    return out


class Sampler:
    def __init__(self, disk_path: str = "/", interval: float = 2.0):
        self.disk_path = disk_path
        self.interval = interval
        self.latest: dict = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="metrics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        prev_cpu = _cpu_times()
        prev_net = _net_bytes()
        prev_t = time.monotonic()
        while not self._stop.wait(self.interval):
            try:
                cpu = _cpu_times()
                net = _net_bytes()
                now = time.monotonic()
                dt = max(now - prev_t, 0.001)
                total = cpu[0] - prev_cpu[0]
                idle = cpu[1] - prev_cpu[1]
                cpu_pct = 0.0 if total <= 0 else max(0.0, min(100.0, 100.0 * (total - idle) / total))
                rx_bps = max(0, net[0] - prev_net[0]) / dt
                tx_bps = max(0, net[1] - prev_net[1]) / dt
                prev_cpu, prev_net, prev_t = cpu, net, now
                self.latest = self.snapshot(cpu_pct, rx_bps, tx_bps)
            except Exception:  # noqa: BLE001
                continue

    def snapshot(self, cpu_pct: float | None = None, rx_bps: float = 0, tx_bps: float = 0) -> dict:
        mem = _meminfo()
        st = os.statvfs(self.disk_path if os.path.exists(self.disk_path) else "/")
        total_mem = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        disk_total = st.f_blocks * st.f_frsize
        disk_free = st.f_bavail * st.f_frsize
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            uptime = 0
        return {
            "cpu_percent": round(cpu_pct, 1) if cpu_pct is not None else None,
            "cpu_cores": os.cpu_count() or 1,
            "load": list(os.getloadavg()),
            "mem_total": total_mem,
            "mem_used": total_mem - avail,
            "mem_percent": round(100.0 * (total_mem - avail) / total_mem, 1) if total_mem else 0,
            "disk_total": disk_total,
            "disk_used": disk_total - disk_free,
            "disk_percent": round(100.0 * (disk_total - disk_free) / disk_total, 1) if disk_total else 0,
            "net_rx_bps": int(rx_bps),
            "net_tx_bps": int(tx_bps),
            "uptime": int(uptime),
            "ts": int(time.time()),
        }

    def current(self) -> dict:
        return self.latest or self.snapshot()
