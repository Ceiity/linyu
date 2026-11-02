"""Unified login error normalisation for NapCat and SnowLuma.

Every rule below is traced to the upstream source it was read from; nothing
here is invented.  Anything that does not match a verified rule is kept as
``UNKNOWN`` together with the raw code / message so the user can still see
exactly what the protocol returned.

NapCat (NapNeko/NapCatQQ, packages/napcat-shell/base.ts and
packages/napcat-webui-backend/src/api/QQLogin.ts):

* ``onQRCodeSessionFailed(errType, errCode)`` – the only pair NapCat itself
  interprets is ``errType == 1 && errCode == 3`` → QR code expired; NapCat then
  sets ``loginError = "二维码已过期，请刷新"`` and requests a new code.  Every
  other pair is only written to the log as
  ``[Core] [Login] Login Error,ErrType:  <t>  ErrCode: <c>``.
* ``onLoginFailed(...args)`` → ``loginError = "登录失败: <JSON args>"``;
  ``args[1]`` carries Tencent's ``serverErrorCode`` and ``message``.
* ``onUserLoggedIn`` → ``"当前账号(<uin>)已登录,无法重复登录"``.
* password / quick login results ``140022008`` (需要验证码),
  ``140022010`` (新设备需要扫码验证), ``140022011`` (异常设备需要验证).
* ``RefreshQRcode`` failures: ``"QRCode Refresh Error: 二维码刷新超时…"``;
  ``GetQQLoginQrcode`` failure: ``"QRCode Get Error"``.
* ``KickedOffLine`` tips, e.g. ``"当前账号已在其它设备登录"``, put the login
  phase into ``reconnecting``.

SnowLuma (SnowLuma/SnowLuma, packages/bridge/src/hook-session.ts,
packages/bridge/src/hook-manager.ts, packages/onebot/src/manager.ts):

* SnowLuma has **no** QR-code / login API: login only happens inside the real
  Linux QQ window (noVNC).  Expiry / rejection are shown inside that window and
  are not reported by SnowLuma, so they cannot be machine-classified.
* Log lines it does emit: ``load failed: PID=<pid> err=<msg>``,
  ``auto-load failed: PID=<pid> err=<msg>``,
  ``QQ runtime unavailable: PID=<pid> err=<msg>``,
  ``initial connection timed out: PID=<pid> …``, ``awaiting login: PID=<pid>``,
  ``login identity discovered: PID=<pid> UIN=<uin>; awaiting readiness``,
  ``session started: UIN=<uin>``, ``session closed: UIN=<uin>``.
"""
from __future__ import annotations

import json
import re
import time

# --------------------------------------------------------------------------
# Normalised catalogue.  ``state`` is the login state-machine state an error of
# this kind ends in (see login_state.py).
# --------------------------------------------------------------------------
CATALOG: dict[str, dict] = {
    "QR_FETCH_FAILED": {
        "title": "二维码获取失败", "state": "FAILED", "retryable": True,
        "description": "协议端没有返回可用的二维码。",
        "suggestion": "确认协议端容器正在运行后点击「重新申请」；多次失败请重启该协议端。",
    },
    "QR_EXPIRED": {
        "title": "二维码已过期", "state": "EXPIRED", "retryable": True,
        "description": "当前二维码已失效。",
        "suggestion": "点击「刷新二维码」或「重新申请」获取新的二维码。",
    },
    "QR_INVALID": {
        "title": "二维码无效", "state": "FAILED", "retryable": True,
        "description": "协议端返回的二维码内容无法使用。",
        "suggestion": "重新申请登录；如持续出现请更新协议端。",
    },
    "USER_REJECTED": {
        "title": "用户拒绝登录", "state": "REJECTED", "retryable": True,
        "description": "手机端拒绝了本次登录。",
        "suggestion": "确认是否本人操作，然后重新发起登录。",
    },
    "USER_CANCELLED": {
        "title": "手机端取消登录", "state": "REJECTED", "retryable": True,
        "description": "手机 QQ 取消了本次登录确认。",
        "suggestion": "重新申请登录，并在手机上点击「登录」确认。",
    },
    "CONFIRM_TIMEOUT": {
        "title": "登录确认超时", "state": "FAILED", "retryable": True,
        "description": "二维码已扫描，但在限定时间内没有完成手机确认。",
        "suggestion": "重新申请登录，扫码后尽快在手机上确认。",
    },
    "NEED_VERIFY": {
        "title": "账号需要进一步验证", "state": "FAILED", "retryable": False,
        "description": "QQ 要求完成验证码等额外验证。",
        "suggestion": "按协议端 WebUI 的提示完成验证，或改用扫码登录。",
    },
    "DEVICE_VERIFY": {
        "title": "设备安全验证", "state": "FAILED", "retryable": False,
        "description": "QQ 判定为新设备，需要扫码完成设备验证。",
        "suggestion": "在协议端 WebUI 中完成新设备验证后再登录。",
    },
    "ENV_ABNORMAL": {
        "title": "登录环境异常", "state": "FAILED", "retryable": False,
        "description": "QQ 判定当前设备或登录环境异常。",
        "suggestion": "按 QQ 提示完成验证；不要频繁更换设备信息或服务器。",
    },
    "NETWORK_ERROR": {
        "title": "网络连接失败", "state": "FAILED", "retryable": True,
        "description": "协议端或 QQ 与服务器之间的网络连接失败。",
        "suggestion": "检查服务器网络后重试。",
    },
    "PROTOCOL_UNREACHABLE": {
        "title": "协议端无响应", "state": "FAILED", "retryable": True,
        "description": "面板连不上协议端（容器未运行、正在重启或端口不可达）。",
        "suggestion": "在「协议端」页面启动或重启该协议端，再重新申请登录。",
    },
    "CLIENT_ERROR": {
        "title": "QQ 客户端异常", "state": "FAILED", "retryable": True,
        "description": "QQ 客户端进程未运行或注入 / 连接失败。",
        "suggestion": "重启协议端；持续失败请在「诊断」页查看详细原因。",
    },
    "LOGIN_DENIED": {
        "title": "登录请求被拒绝", "state": "REJECTED", "retryable": False,
        "description": "QQ 服务端拒绝了本次登录请求。",
        "suggestion": "查看原始错误信息；稍后再试或在手机 QQ 上确认账号状态。",
    },
    "ACCOUNT_RESTRICTED": {
        "title": "账号暂时无法登录", "state": "FAILED", "retryable": False,
        "description": "账号被冻结、限制或暂时不允许登录。",
        "suggestion": "在手机 QQ 中查看账号安全状态，处理后再登录。",
    },
    "KICKED_OFFLINE": {
        "title": "账号被迫下线", "state": "FAILED", "retryable": True,
        "description": "账号在其他设备登录或被服务端下线。",
        "suggestion": "确认没有其他设备 / 协议端占用同一账号，然后重新登录。",
    },
    "ACCOUNT_OFFLINE": {
        "title": "账号已离线", "state": "FAILED", "retryable": True,
        "description": "协议端报告 QQ 会话已关闭。",
        "suggestion": "点击「重新申请」重新登录。",
    },
    "ALREADY_LOGGED_IN": {
        "title": "账号已登录", "state": "SUCCESS", "retryable": False,
        "description": "该协议端上的 QQ 已经在线，无需重复登录。",
        "suggestion": "无需操作。",
    },
    "UNKNOWN": {
        "title": "服务端返回未知错误", "state": "FAILED", "retryable": True,
        "description": "协议端返回了未归类的错误，原始信息已保留。",
        "suggestion": "查看原始错误码和消息；可重试或到「诊断」页排查。",
    },
}

# Verified NapCat numeric results (napcat-shell/base.ts passwordLogin / captcha / new-device flows).
NAPCAT_RESULT_CODES = {
    "140022008": "NEED_VERIFY",     # 需要验证码 (proofWaterUrl)
    "140022010": "DEVICE_VERIFY",   # 新设备需要扫码验证 (jumpUrl)
    "140022011": "ENV_ABNORMAL",    # 异常设备需要验证 (jumpUrl)
}

# Verified NapCat (errType, errCode) pairs from onQRCodeSessionFailed.
NAPCAT_QR_SESSION_CODES = {
    (1, 3): "QR_EXPIRED",
}

# Classification of Tencent's free-text ``message`` (from onLoginFailed / kick
# tips).  This does not invent codes: the raw serverErrorCode is always kept,
# the message text only selects the human category.  Order matters.
MESSAGE_RULES: list[tuple[str, str]] = [
    (r"已登录.*无法重复登录|已经登录", "ALREADY_LOGGED_IN"),
    (r"二维码.*(过期|失效)|qrcode.*expired", "QR_EXPIRED"),
    (r"其它设备登录|其他设备登录|下线通知|被踢|踢下线|kicked", "KICKED_OFFLINE"),
    (r"拒绝", "USER_REJECTED"),
    (r"取消", "USER_CANCELLED"),
    (r"冻结|封禁|封停|限制登录|暂时无法登录|暂停使用|违规", "ACCOUNT_RESTRICTED"),
    (r"新设备", "DEVICE_VERIFY"),
    (r"异常设备|环境异常|登录环境|存在风险|安全风险", "ENV_ABNORMAL"),
    (r"验证码|安全验证|需要验证", "NEED_VERIFY"),
    (r"超时|timeout|timed out", "CONFIRM_TIMEOUT"),
    (r"网络|network|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|socket", "NETWORK_ERROR"),
    (r"二维码.*(获取|刷新).*(失败|超时|错误)|QRCode (Get|Refresh) Error", "QR_FETCH_FAILED"),
]

NAPCAT_ERRTYPE_RE = re.compile(r"Login Error\s*,\s*ErrType:\s*(-?\d+)\s*ErrCode:\s*(-?\d+)", re.I)
NAPCAT_LOGINFAIL_RE = re.compile(r"Login Error\s*,\s*ErrInfo:\s*(.+)$", re.I)


def make_error(code: str, protocol: str, stage: str = "", raw_code: str = "", raw_message: str = "",
               classified_by: str = "", extra: dict | None = None) -> dict:
    meta = CATALOG.get(code) or CATALOG["UNKNOWN"]
    if code not in CATALOG:
        code = "UNKNOWN"
    out = {
        "code": code,
        "title": meta["title"],
        "description": meta["description"],
        "suggestion": meta["suggestion"],
        "state": meta["state"],
        "retryable": meta["retryable"],
        "protocol": protocol,
        "stage": stage,
        "raw_code": str(raw_code or ""),
        "raw_message": str(raw_message or "")[:2000],
        "classified_by": classified_by or ("default" if code == "UNKNOWN" else "rule"),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
    }
    if extra:
        out["extra"] = extra
    return out


def classify_message(text: str) -> str:
    raw = str(text or "")
    for pattern, code in MESSAGE_RULES:
        if re.search(pattern, raw, re.I):
            return code
    return ""


def parse_napcat_login_error(text: str, stage: str = "") -> dict | None:
    """Normalise NapCat's ``loginError`` string (CheckLoginStatus.data.loginError)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    raw_code = ""
    message = raw
    classified_by = "message"
    if raw.startswith("登录失败:") or raw.startswith("登录失败："):
        payload = re.split(r"[:：]", raw, maxsplit=1)[1].strip()
        try:
            args = json.loads(payload)
        except Exception:
            args = None
        info = None
        if isinstance(args, list):
            # NapCat's own frontend reads args[1]; fall back to the first dict that looks like an error.
            if len(args) > 1 and isinstance(args[1], dict):
                info = args[1]
            else:
                info = next((a for a in args if isinstance(a, dict) and (a.get("message") or a.get("serverErrorCode") or a.get("errMsg"))), None)
        if isinstance(info, dict):
            message = str(info.get("message") or info.get("errMsg") or "登录失败")
            raw_code = str(info.get("serverErrorCode") or info.get("errCode") or info.get("result") or "")
    if raw_code in NAPCAT_RESULT_CODES:
        return make_error(NAPCAT_RESULT_CODES[raw_code], "napcat", stage, raw_code, raw, "code")
    code = classify_message(message)
    if not code:
        code = "UNKNOWN"
        classified_by = "default"
    err = make_error(code, "napcat", stage, raw_code, raw if message == raw else "%s | %s" % (message, raw), classified_by)
    return err


def parse_napcat_log(text: str, stage: str = "") -> list[dict]:
    """Extract login errors from NapCat container logs (only lines NapCat really prints)."""
    found: list[dict] = []
    for line in str(text or "").splitlines():
        m = NAPCAT_ERRTYPE_RE.search(line)
        if m:
            et, ec = int(m.group(1)), int(m.group(2))
            code = NAPCAT_QR_SESSION_CODES.get((et, ec), "UNKNOWN")
            found.append(make_error(code, "napcat", stage, "ErrType=%d ErrCode=%d" % (et, ec), line.strip(),
                                    "code" if code != "UNKNOWN" else "default", {"err_type": et, "err_code": ec}))
            continue
        m = NAPCAT_LOGINFAIL_RE.search(line)
        if m:
            err = parse_napcat_login_error("登录失败: " + m.group(1).strip(), stage)
            if err:
                found.append(err)
    return found


SNOWLUMA_LOG_RULES: list[tuple[re.Pattern, str, str]] = [
    # (pattern, kind, code)  kind: "progress" or "error"
    (re.compile(r"awaiting login: PID=(\d+)"), "awaiting", ""),
    (re.compile(r"login identity discovered: PID=(\d+) UIN=(\d+)"), "identity", ""),
    (re.compile(r"session started: UIN=(\d+)"), "session_started", ""),
    (re.compile(r"session closed: UIN=(\d+)"), "session_closed", "ACCOUNT_OFFLINE"),
    (re.compile(r"auto-load failed: PID=(\d+) err=(.*)$"), "error", "CLIENT_ERROR"),
    (re.compile(r"load failed: PID=(\d+) err=(.*)$"), "error", "CLIENT_ERROR"),
    (re.compile(r"QQ runtime unavailable: PID=(\d+) err=(.*)$"), "error", "CLIENT_ERROR"),
    (re.compile(r"initial connection timed out: PID=(\d+)(.*)$"), "error", "CLIENT_ERROR"),
]


def parse_snowluma_log(text: str, stage: str = "") -> list[dict]:
    """Return ordered SnowLuma login events found in container logs."""
    events: list[dict] = []
    for line in str(text or "").splitlines():
        for pattern, kind, code in SNOWLUMA_LOG_RULES:
            m = pattern.search(line)
            if not m:
                continue
            ev = {"kind": kind, "line": line.strip()[:500]}
            if kind in {"identity"}:
                ev["uin"] = m.group(2)
            elif kind in {"session_started", "session_closed"}:
                ev["uin"] = m.group(1)
            if code:
                ev["error"] = make_error(code, "snowluma", stage, "", line.strip(), "log")
            events.append(ev)
            break
    return events


def catalog_table() -> dict:
    """Mapping table shown in the UI / docs."""
    rows = []
    for code, meta in CATALOG.items():
        rows.append({"code": code, **meta})
    sources = []
    for raw, code in NAPCAT_RESULT_CODES.items():
        sources.append({"protocol": "napcat", "raw": raw, "code": code})
    for (et, ec), code in NAPCAT_QR_SESSION_CODES.items():
        sources.append({"protocol": "napcat", "raw": "ErrType=%d ErrCode=%d" % (et, ec), "code": code})
    for pattern, kind, code in SNOWLUMA_LOG_RULES:
        if code:
            sources.append({"protocol": "snowluma", "raw": pattern.pattern, "code": code})
    return {"codes": rows, "sources": sources}
