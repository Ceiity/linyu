// NapCat 监听开关、本地管理脚本、日志刷新、端口状态、WebUI/二维码/检测命令
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static void StartNapcatListeningNow(bool automatic) {
    if (g_app.napcatRunning.load()) return;
    if (!IsTcpPortListening(3001)) {
        std::wstring text = IsTcpPortListening(6099)
            ? L"检测到 WebUI 6099，但 OneBot 3001 还没启动。请完成 NapCat 扫码/授权。"
            : L"未检测到 NapCat 端口。请先到 NapCat 页启动。";
        if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, text.c_str());
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, text.c_str());
        return;
    }

    std::wstring url = Trim(GetWindowTextString(g_app.napcatUrlEdit));
    if (url.empty()) {
        url = L"ws://127.0.0.1:3001";
        SetWindowTextW(g_app.napcatUrlEdit, url.c_str());
    }
    std::wstring token = GetWindowTextString(g_app.napcatTokenEdit);
    bool onlyAt = g_app.napcatOnlyAtChecked;
    SaveConfig();
    g_app.napcatRunning = true;
    if (g_app.napcatToggleButton) SetWindowTextW(g_app.napcatToggleButton, L"停止监听");
    if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, automatic ? L"检测到 NapCat 在线，正在自动连接监听。" : L"NapCat 正在连接。");
    std::thread(NapcatListenThread, url, token, onlyAt).detach();
}

static void ToggleNapcatListening() {
    if (g_app.napcatRunning.load()) {
        g_app.napcatRunning = false;
        if (g_app.napcatToggleButton) SetWindowTextW(g_app.napcatToggleButton, L"连接监听");
        if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, L"NapCat 正在停止监听。");
        return;
    }
    StartNapcatListeningNow(false);
}

static std::wstring DefaultQqPath() {
    if (GetFileAttributesW(L"D:\\qq\\QQ.exe") != INVALID_FILE_ATTRIBUTES) return L"D:\\qq\\QQ.exe";
    return L"";
}

static std::wstring NapcatManagerScriptPath() {
    return ConfigDir() + L"\\napcat_manager.ps1";
}

static std::wstring NapcatLogPath() {
    return ConfigDir() + L"\\napcat_live_utf8.log";
}

static void TrimNapcatLogFile() {
    std::wstring path = NapcatLogPath();
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 1024 * 1024) {
        CloseHandle(file);
        return;
    }
    DWORD keep = 384 * 1024;
    LARGE_INTEGER distance{};
    distance.QuadPart = size.QuadPart - keep;
    SetFilePointerEx(file, distance, nullptr, FILE_BEGIN);
    std::string bytes(keep, '\0');
    DWORD read = 0;
    ReadFile(file, bytes.data(), keep, &read, nullptr);
    CloseHandle(file);
    if (read == 0) return;
    bytes.resize(read);
    HANDLE out = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (out == INVALID_HANDLE_VALUE) return;
    static const char marker[] = "\r\n--- log trimmed to avoid disk growth ---\r\n";
    DWORD written = 0;
    WriteFile(out, marker, static_cast<DWORD>(sizeof(marker) - 1), &written, nullptr);
    WriteFile(out, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr);
    CloseHandle(out);
    g_app.displayedNapcatLog.clear();
}

static bool AppendNapcatLogLine(const std::wstring& line) {
    TrimNapcatLogFile();
    std::wstring existing = ReadTextFile(NapcatLogPath());
    std::wstring prefix = (!existing.empty() && existing.back() != L'\n' && existing.back() != L'\r') ? L"\r\n" : L"";
    std::string text = WideToUtf8(prefix + line + L"\r\n");
    HANDLE file = CreateFileW(NapcatLogPath().c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    if (!text.empty()) WriteFile(file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr);
    CloseHandle(file);
    return text.empty() || written == text.size();
}

static std::wstring NapcatQrPath() {
    wchar_t localAppData[MAX_PATH]{};
    DWORD len = GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, MAX_PATH);
    std::wstring base = (len > 0 && len < MAX_PATH) ? std::wstring(localAppData) : ExeDir();
    return base + L"\\LinyuKouziShou\\NapCatNode\\Node\\napcat\\cache\\qrcode.png";
}

static void WriteAsciiFile(const std::wstring& path, const std::string& text) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw std::runtime_error("create script failed");
    DWORD written = 0;
    if (!text.empty()) WriteFile(file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr);
    CloseHandle(file);
}

static void WriteNapcatManagerScript() {
    static const char* script = R"PS1(
param(
  [string]$Mode = "start",
  [string]$QQPath = "D:\qq\QQ.exe",
  [string]$LogPath = ""
)
$ErrorActionPreference = "Stop"
if (!$LogPath) { $LogPath = Join-Path $env:APPDATA "LinyuKouziShou\napcat_live_utf8.log" }
$logDir = Split-Path $LogPath -Parent
if ($logDir) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$EscChar = [char]27
function TrimLogFile {
  try {
    if ((Test-Path -LiteralPath $LogPath) -and ((Get-Item -LiteralPath $LogPath).Length -gt 1048576)) {
      $bytes = [System.IO.File]::ReadAllBytes($LogPath)
      $keep = [Math]::Min(393216, $bytes.Length)
      $newBytes = New-Object byte[] ($keep)
      [Array]::Copy($bytes, $bytes.Length - $keep, $newBytes, 0, $keep)
      [System.IO.File]::WriteAllText($LogPath, "--- log trimmed to avoid disk growth ---`r`n", $script:Utf8NoBom)
      $stream = [System.IO.File]::Open($LogPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
      try { $stream.Write($newBytes, 0, $newBytes.Length) } finally { $stream.Close() }
    }
  } catch {
  }
}
function LogLine([string]$Text) {
  try {
    if ($null -eq $Text) { return }
    TrimLogFile
    $Text = [regex]::Replace($Text, ($script:EscChar + "\[[0-9;]*[A-Za-z]"), "")
    $line = "$(Get-Date -Format 'HH:mm:ss') $Text`r`n"
    [System.IO.File]::AppendAllText($LogPath, $line, $script:Utf8NoBom)
  } catch {
  }
}

function Quote-Arg([string]$Text) {
  if ($null -eq $Text) { return '""' }
  return '"' + ($Text -replace '\\', '\\' -replace '"', '\"') + '"'
}

function Run-NapCatNative([string]$Launcher, [string]$QQ, [string]$Hook) {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $Launcher
  $psi.Arguments = (Quote-Arg $QQ) + " " + (Quote-Arg $Hook)
  $psi.WorkingDirectory = Split-Path $Launcher -Parent
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
  $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  $handler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($eventArgs.Data) { LogLine $eventArgs.Data }
  }
  $proc.add_OutputDataReceived($handler)
  $proc.add_ErrorDataReceived($handler)
  [void]$proc.Start()
  $proc.BeginOutputReadLine()
  $proc.BeginErrorReadLine()
  LogLine ("NapCat process PID=" + $proc.Id)
  $proc.WaitForExit()
  LogLine ("NapCat process exited. Code=" + $proc.ExitCode)
}

LogLine "----- NapCat manager started. Mode=$Mode -----"
try {
  $root = Join-Path $env:LOCALAPPDATA "LinyuKouziShou\NapCatNode"
  $zip = Join-Path $root "NapCat.Shell.Windows.Node.zip"
  $base = Join-Path $root "Node"
  $napcat = Join-Path $base "napcat"
  $configDir = Join-Path $napcat "config"
  $onebot = Join-Path $configDir "onebot11.json"
  New-Item -ItemType Directory -Force -Path $root | Out-Null
  LogLine "Root: $root"

  if (!(Test-Path (Join-Path $base "node.exe")) -or !(Test-Path (Join-Path $napcat "NapCatWinBootMain.exe"))) {
    LogLine "NapCat files are missing. Fetching latest release metadata..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{ "User-Agent" = "LinyuKouziShou" }
    $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -eq "NapCat.Shell.Windows.Node.zip" } | Select-Object -First 1
    if (!$asset) { throw "NapCat.Shell.Windows.Node.zip not found in release assets" }
    LogLine "Downloading NapCat $($release.tag_name)..."
    Invoke-WebRequest -Headers $headers -Uri $asset.browser_download_url -OutFile $zip
    LogLine "Download complete: $zip"
    if (Test-Path $base) {
      LogLine "Removing old Node folder..."
      Remove-Item -LiteralPath $base -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $base | Out-Null
    LogLine "Extracting NapCat..."
    Expand-Archive -LiteralPath $zip -DestinationPath $base -Force
    LogLine "Extract complete."
  } else {
    LogLine "NapCat files already exist."
  }

  New-Item -ItemType Directory -Force -Path $configDir | Out-Null
  LogLine "Writing OneBot config: $onebot"
  @'
{
  "network": {
    "httpServers": [
      {
        "enable": true,
        "name": "HTTP",
        "host": "127.0.0.1",
        "port": 3000,
        "enableCors": true,
        "enableWebsocket": false,
        "messagePostFormat": "array",
        "token": "",
        "debug": false
      }
    ],
    "httpSseServers": [],
    "httpClients": [],
    "websocketServers": [
      {
        "enable": true,
        "name": "WebSocket",
        "host": "127.0.0.1",
        "port": 3001,
        "reportSelfMessage": false,
        "enableForcePushEvent": true,
        "messagePostFormat": "array",
        "token": "",
        "debug": false,
        "heartInterval": 30000
      }
    ],
    "websocketClients": [],
    "plugins": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": false,
  "parseMultMsg": false,
  "imageDownloadProxy": ""
}
'@ | Set-Content -LiteralPath $onebot -Encoding UTF8

  if ($Mode -eq "install") {
    LogLine "Install/repair finished. OneBot WebSocket is configured on ws://127.0.0.1:3001/"
    exit 0
  }

  if (!(Test-Path $QQPath)) {
    throw "QQ.exe not found: $QQPath"
  }

  $env:NAPCAT_PATCH_PACKAGE = Join-Path $napcat "qqnt.json"
  $env:NAPCAT_LOAD_PATH = Join-Path $napcat "loadNapCat.js"
  $env:NAPCAT_INJECT_PATH = Join-Path $napcat "NapCatWinBootHook.dll"
  $launcher = Join-Path $napcat "NapCatWinBootMain.exe"
  $main = (Join-Path $napcat "napcat.mjs").Replace("\", "/")
  '(async () => {await import("file:///' + $main + '")})()' | Set-Content -LiteralPath $env:NAPCAT_LOAD_PATH -Encoding ASCII

  LogLine "Starting NapCat with QQ: $QQPath"
  LogLine "Launcher: $launcher"
  LogLine "QR image will be saved to: $(Join-Path $napcat 'cache\qrcode.png')"
  Run-NapCatNative $launcher $QQPath $env:NAPCAT_INJECT_PATH
} catch {
  LogLine ("ERROR: " + $_.Exception.Message)
  if ($_.ScriptStackTrace) { LogLine ($_.ScriptStackTrace) }
  exit 1
}
)PS1";
    WriteAsciiFile(NapcatManagerScriptPath(), script);
}

static std::wstring PowerShellExePath() {
    wchar_t systemDir[MAX_PATH]{};
    if (GetSystemDirectoryW(systemDir, MAX_PATH)) {
        std::wstring path = std::wstring(systemDir) + L"\\WindowsPowerShell\\v1.0\\powershell.exe";
        if (GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES) return path;
    }
    return L"powershell.exe";
}

static void RefreshNapcatLog();
static void ColorizeNapcatLog();

static void RunNapcatManager(const wchar_t* mode) {
    try {
        std::wstring modeText = wcscmp(mode, L"install") == 0 ? L"install/repair" : L"start";
        std::wstring clickLine = L"[Linyu] Button clicked: " + modeText + L". Preparing manager script...";
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"已收到点击，正在准备 NapCat 管理器。");
        if (g_app.status) SetWindowTextW(g_app.status, L"NapCat 按钮已触发。");
        if (AppendNapcatLogLine(clickLine)) {
            RefreshNapcatLog();
        } else if (g_app.napcatLogEdit) {
            std::wstring fallback = L"日志文件暂时写不进去，但按钮已经触发。\r\n" + clickLine;
            g_app.displayedNapcatLog = fallback;
            SetWindowTextW(g_app.napcatLogEdit, fallback.c_str());
        }
        WriteNapcatManagerScript();
        std::wstring qqPath = Trim(GetWindowTextString(g_app.napcatQqPathEdit));
        if (qqPath.empty()) qqPath = DefaultQqPath();
        std::wstring args = L"-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + NapcatManagerScriptPath()
            + L"\" -Mode \"" + mode + L"\" -QQPath \"" + qqPath + L"\" -LogPath \"" + NapcatLogPath() + L"\"";
        std::wstring psPath = PowerShellExePath();
        SHELLEXECUTEINFOW sei{ sizeof(sei) };
        sei.fMask = SEE_MASK_NOCLOSEPROCESS;
        sei.lpVerb = L"open";
        sei.lpFile = psPath.c_str();
        sei.lpParameters = args.c_str();
        sei.nShow = SW_HIDE;
        if (!ShellExecuteExW(&sei)) throw std::runtime_error("launch powershell failed");
        DWORD pid = sei.hProcess ? GetProcessId(sei.hProcess) : 0;
        if (pid) {
            AppendNapcatLogLine(L"[Linyu] Manager process started. PID=" + std::to_wstring(pid));
            CloseHandle(sei.hProcess);
        } else {
            AppendNapcatLogLine(L"[Linyu] Manager process started.");
        }
        RefreshNapcatLog();
        if (wcscmp(mode, L"start") == 0) {
            g_app.napcatLoggedIn = false;
            g_app.napcatQrVisible = true;
            ShowNapcatQrWindow();
        }
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus,
            wcscmp(mode, L"install") == 0 ? L"正在后台安装/修复 NapCat，下面会显示日志。" : L"正在后台启动 NapCat，二维码会显示在扫码窗口。");
    } catch (const std::exception& ex) {
        std::wstring msg = L"NapCat 管理失败：" + ExceptionMessageToWide(ex);
        AppendNapcatLogLine(L"[Linyu] ERROR: " + msg);
        RefreshNapcatLog();
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, msg.c_str());
        MessageBoxW(g_app.hwnd, msg.c_str(), APP_TITLE, MB_OK | MB_ICONERROR);
    }
}

static void RefreshNapcatLog() {
    if (!g_app.napcatLogEdit) return;
    if (g_app.activePage != 2) {
        ShowWindow(g_app.napcatLogEdit, SW_HIDE);
        return;
    }
    ShowWindow(g_app.napcatLogEdit, SW_SHOW);
    std::wstring log = NormalizeNapcatLogText(ReadTextFile(NapcatLogPath()));
    if (log.empty()) {
        log = L"暂无日志。点“安装/修复 NapCat”或“启动 NapCat”后这里会显示输出。";
    }
    constexpr size_t maxChars = 12000;
    if (log.size() > maxChars) log = log.substr(log.size() - maxChars);

    bool loggedIn = log.find(L"登录成功") != std::wstring::npos
        || log.find(L"登录完成") != std::wstring::npos
        || log.find(L"Login Success") != std::wstring::npos;
    if (loggedIn && !g_app.napcatLoggedIn) {
        g_app.napcatLoggedIn = true;
        g_app.napcatQrVisible = false;
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"NapCat 看起来已经启动成功。去 AI 页点“连接监听”。");
        InvalidateNapcatQrCard();
    }

    if (log == g_app.displayedNapcatLog) return;

    SendMessageW(g_app.napcatLogEdit, WM_SETREDRAW, FALSE, 0);
    if (!g_app.displayedNapcatLog.empty()
        && log.size() > g_app.displayedNapcatLog.size()
        && log.compare(0, g_app.displayedNapcatLog.size(), g_app.displayedNapcatLog) == 0) {
        std::wstring delta = log.substr(g_app.displayedNapcatLog.size());
        int oldLen = GetWindowTextLengthW(g_app.napcatLogEdit);
        SendMessageW(g_app.napcatLogEdit, EM_SETSEL, oldLen, oldLen);
        SendMessageW(g_app.napcatLogEdit, EM_REPLACESEL, FALSE, reinterpret_cast<LPARAM>(delta.c_str()));
    } else {
        SetWindowTextW(g_app.napcatLogEdit, log.c_str());
    }
    g_app.displayedNapcatLog = log;
    int len = GetWindowTextLengthW(g_app.napcatLogEdit);
    int lineCount = static_cast<int>(SendMessageW(g_app.napcatLogEdit, EM_GETLINECOUNT, 0, 0));
    SendMessageW(g_app.napcatLogEdit, EM_SETSEL, len, len);
    SendMessageW(g_app.napcatLogEdit, EM_LINESCROLL, 0, lineCount);
    SendMessageW(g_app.napcatLogEdit, WM_VSCROLL, SB_BOTTOM, 0);
    SendMessageW(g_app.napcatLogEdit, EM_SCROLLCARET, 0, 0);
    SendMessageW(g_app.napcatLogEdit, WM_SETREDRAW, TRUE, 0);
    ColorizeNapcatLog();
    RedrawWindow(g_app.napcatLogEdit, nullptr, nullptr, RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME);
}

static void RefreshNapcatPortState() {
    bool webUiOnline = IsTcpPortListening(6099);
    bool oneBotOnline = IsTcpPortListening(3001);

    if (oneBotOnline) {
        if (!g_app.napcatOneBotOnline) {
            g_app.napcatOneBotOnline = true;
            g_app.napcatLoggedIn = true;
            CloseNapcatQrWindow();
            if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"NapCat OneBot 已上线，正在自动连接监听。");
            AppendNapcatLogLine(L"[Linyu] OneBot 3001 is online. Auto listening...");
        }
        ULONGLONG now = GetTickCount64();
        if (!g_app.napcatRunning.load() && now - g_app.lastNapcatAutoListenTick > 5000) {
            g_app.lastNapcatAutoListenTick = now;
            StartNapcatListeningNow(true);
        }
        return;
    }

    if (g_app.napcatOneBotOnline) {
        g_app.napcatOneBotOnline = false;
        if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, L"OneBot 3001 已断开，等待 NapCat 重新上线。");
        AppendNapcatLogLine(L"[Linyu] OneBot 3001 went offline.");
    }
    if (webUiOnline && !g_app.napcatRunning.load()) {
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"WebUI 6099 已启动，但 OneBot 3001 还没上线。请完成扫码/授权。");
    }
}

static void OpenNapcatWebUi() {
    if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"WebUI 地址会在日志里显示，通常是 http://127.0.0.1:6099/webui?token=...");
    RefreshNapcatLog();
}

static void OpenNapcatQr() {
    g_app.napcatQrVisible = true;
    std::wstring path = NapcatQrPath();
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"还没找到二维码。请先启动 NapCat，等日志提示 qrcode.png。");
        ShowNapcatQrWindow();
        InvalidateNapcatQrCard();
        return;
    }
    if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"二维码已显示在扫码窗口，请用手机 QQ 扫码。");
    ShowNapcatQrWindow();
}

static void ShowNapcatCheckCommand() {
    std::wstring logPath = NapcatLogPath();
    std::wstring command = L"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command \""
        L"$p='" + logPath + L"';"
        L"Add-Content -LiteralPath $p -Encoding UTF8 -Value '[Linyu] Port check:';"
        L"$r=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in 3001,3000,6099} | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize | Out-String;"
        L"if([string]::IsNullOrWhiteSpace($r)){Add-Content -LiteralPath $p -Encoding UTF8 -Value '[Linyu] No NapCat ports are listening.'}else{Add-Content -LiteralPath $p -Encoding UTF8 -Value $r}\"";
    ShellExecuteW(g_app.hwnd, L"open", L"powershell.exe", command.c_str(), nullptr, SW_HIDE);
    if (g_app.napcatManagerStatus) SetWindowTextW(g_app.napcatManagerStatus, L"正在后台检测端口，结果会写到下面日志。");
    RefreshNapcatLog();
}

static COLORREF NapcatLogLineColor(const std::wstring& line) {
    std::wstring lower = line;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](wchar_t ch) { return static_cast<wchar_t>(towlower(ch)); });
    if (lower.find(L"[error") != std::wstring::npos || lower.find(L" error") != std::wstring::npos || lower.find(L"失败") != std::wstring::npos) {
        return RGB(255, 59, 48);
    }
    if (lower.find(L"[warn") != std::wstring::npos || lower.find(L" warn") != std::wstring::npos || lower.find(L"二维码") != std::wstring::npos) {
        return RGB(176, 112, 0);
    }
    if (lower.find(L"[qq]") != std::wstring::npos || lower.find(L"接收") != std::wstring::npos || lower.find(L"发送") != std::wstring::npos) {
        return C_ACCENT;
    }
    if (lower.find(L"[linyu]") != std::wstring::npos) {
        return RGB(88, 86, 214);
    }
    if (lower.find(L"[info") != std::wstring::npos || lower.find(L"online") != std::wstring::npos || lower.find(L"initialized") != std::wstring::npos) {
        return RGB(36, 138, 61);
    }
    return C_TEXT;
}

static void SetRichTextColorRange(HWND hwnd, LONG start, LONG end, COLORREF color) {
    CHARRANGE range{ start, end };
    SendMessageW(hwnd, EM_EXSETSEL, 0, reinterpret_cast<LPARAM>(&range));
    CHARFORMAT2W cf{};
    cf.cbSize = sizeof(cf);
    cf.dwMask = CFM_COLOR;
    cf.crTextColor = color;
    SendMessageW(hwnd, EM_SETCHARFORMAT, SCF_SELECTION, reinterpret_cast<LPARAM>(&cf));
}

static void ColorizeNapcatLog() {
    if (!g_app.napcatLogRich || !g_app.napcatLogEdit) return;
    const std::wstring& text = g_app.displayedNapcatLog;
    SendMessageW(g_app.napcatLogEdit, WM_SETREDRAW, FALSE, 0);
    SetRichTextColorRange(g_app.napcatLogEdit, 0, -1, C_TEXT);
    size_t start = 0;
    while (start < text.size()) {
        size_t end = text.find_first_of(L"\r\n", start);
        if (end == std::wstring::npos) end = text.size();
        if (end > start) {
            COLORREF color = NapcatLogLineColor(text.substr(start, end - start));
            if (color != C_TEXT) {
                SetRichTextColorRange(g_app.napcatLogEdit, static_cast<LONG>(start), static_cast<LONG>(end), color);
            }
        }
        while (end < text.size() && (text[end] == L'\r' || text[end] == L'\n')) ++end;
        start = end;
    }
    LONG len = static_cast<LONG>(text.size());
    CHARRANGE bottom{ len, len };
    SendMessageW(g_app.napcatLogEdit, EM_EXSETSEL, 0, reinterpret_cast<LPARAM>(&bottom));
    SendMessageW(g_app.napcatLogEdit, WM_SETREDRAW, TRUE, 0);
    RedrawWindow(g_app.napcatLogEdit, nullptr, nullptr, RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME);
}
