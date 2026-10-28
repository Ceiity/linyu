"""日志脱敏与中文提示。"""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"(?i)(\"?(?:token|password|passwd|secret|credential|api[_-]?key|access_token|jwt_secret)\"?\s*[:=]\s*\"?)([^\s\",}&]{4,})"), r"\1******"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1******"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "******"),
    (re.compile(r"([?&](?:token|access_token|key)=)[^&\s]+", re.I), r"\1******"),
]

_secrets: set[str] = set()


def add_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        _secrets.add(value)


def redact(text: str) -> str:
    for s in _secrets:
        if s in text:
            text = text.replace(s, "******")
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text


_LEVELS = [
    ("ERROR", re.compile(r"\[(?:ERRO|ERROR|CRIT|CRITICAL|FATAL)\]|\b(?:ERROR|Traceback|Exception)\b|\[error\]", re.I)),
    ("WARNING", re.compile(r"\[(?:WARN|WARNING)\]|\bWARN(?:ING)?\b|\[warn\]", re.I)),
    ("DEBUG", re.compile(r"\[(?:DEBG|DEBUG)\]|\bDEBUG\b|\[debug\]", re.I)),
]

_HINTS = [
    (re.compile(r"aiocqhttp.*(?:连接|connect)", re.I), "NapCat 已连接到 AstrBot"),
    (re.compile(r"二维码|qrcode", re.I), "等待扫码登录 QQ"),
    (re.compile(r"登录成功|login success", re.I), "QQ 登录成功"),
    (re.compile(r"WebUI.*(?:启动|started|running)", re.I), "WebUI 已启动"),
    (re.compile(r"插件.*(?:载入|加载|loaded)", re.I), "插件已加载"),
    (re.compile(r"(?:token|鉴权).*(?:失败|invalid|错误)", re.I), "连接 Token 不匹配"),
    (re.compile(r"Connection refused|ECONNREFUSED", re.I), "连接被拒绝，对端服务可能未启动"),
    (re.compile(r"Traceback", re.I), "程序出现异常"),
]


def level_of(line: str) -> str:
    for name, pat in _LEVELS:
        if pat.search(line):
            return name
    return "INFO"


def hint_of(line: str) -> str:
    for pat, text in _HINTS:
        if pat.search(line):
            return text
    return ""


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def parse_line(raw: str) -> dict:
    """Docker 时间戳行 → {time, level, text, hint}。"""
    ts = ""
    text = raw
    if len(raw) > 30 and raw[4] == "-" and "T" in raw[:20]:
        ts, _, text = raw.partition(" ")
    text = redact(strip_ansi(text.rstrip("\r")))
    return {"time": ts[:19].replace("T", " "), "level": level_of(text), "text": text, "hint": hint_of(text)}
