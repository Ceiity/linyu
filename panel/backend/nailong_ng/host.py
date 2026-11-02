"""The bridge between the NG modules and the legacy panel (app.py).

``app.py`` builds one :class:`Host` with the real implementations; unit tests
build one with fakes.  Keeping this explicit avoids circular imports and keeps
the NG modules runnable without Docker.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Host:
    install_prefix: Path
    project_dir: Path
    # run(args, timeout, input_text=None) -> (code, output)
    run: Callable[..., tuple[int, str]]
    # docker(args, timeout) -> (code, output)
    docker: Callable[..., tuple[int, str]]
    # bash(script, timeout) -> (code, output); sources lib/ops.sh + state
    bash: Callable[..., tuple[int, str]]
    # shell_state() -> dict of /opt/astrbot/.env
    shell_state: Callable[[], dict]
    # audit(user, action, detail, ok)
    audit: Callable[..., None]
    # NapCat helpers already implemented by the legacy panel
    napcat_rows: Callable[[], list[dict]] = lambda: []
    napcat_webui_call: Callable[..., dict] | None = None
    redact: Callable[[str], str] = lambda s: s
    # busy(slot) -> str: non-empty reason when a critical task touches the slot
    busy: Callable[[str], str] = lambda slot: ""
    extra: dict = field(default_factory=dict)

    @property
    def state(self) -> dict:
        try:
            return self.shell_state() or {}
        except Exception:
            return {}

    def path(self, key: str, default: Path) -> Path:
        value = self.state.get(key)
        return Path(value) if value else default

    @property
    def network(self) -> str:
        return self.state.get("NETWORK_NAME") or "astrbot_network"

    @property
    def astrbot_container(self) -> str:
        return self.state.get("ASTRBOT_CONTAINER") or "astrbot"

    @property
    def reverse_token(self) -> str:
        return self.state.get("ASTRBOT_REVERSE_WS_TOKEN") or ""

    @property
    def napcat_base(self) -> Path:
        return self.path("NAPCAT_BASE_DIR", self.install_prefix / "napcat")

    @property
    def data_dir(self) -> Path:
        return self.path("DATA_DIR", self.install_prefix / "data")

    @property
    def in_docker(self) -> bool:
        return Path("/.dockerenv").exists() or os.environ.get("NAILONG_PANEL_IN_DOCKER") == "1"
