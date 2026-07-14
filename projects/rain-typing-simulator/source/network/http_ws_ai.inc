// WinHTTP 读取、QQ 头像请求、NapCat WebSocket 监听、DeepSeek HTTP 调用
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static std::string WinHttpReadAll(HINTERNET request) {
    std::string body;
    DWORD available = 0;
    do {
        if (!WinHttpQueryDataAvailable(request, &available)) break;
        if (!available) break;
        std::string chunk(available, '\0');
        DWORD read = 0;
        if (!WinHttpReadData(request, chunk.data(), available, &read)) break;
        chunk.resize(read);
        body += chunk;
    } while (available > 0);
    return body;
}

struct WsTarget {
    bool secure = false;
    std::wstring host;
    INTERNET_PORT port = 0;
    std::wstring path = L"/";
};

static bool StartsWithNoCase(const std::wstring& text, const std::wstring& prefix) {
    if (text.size() < prefix.size()) return false;
    for (size_t i = 0; i < prefix.size(); ++i) {
        if (towlower(text[i]) != towlower(prefix[i])) return false;
    }
    return true;
}

static WsTarget ParseWsUrl(std::wstring url) {
    url = Trim(url);
    if (url.empty()) url = L"ws://127.0.0.1:3001";
    WsTarget target;
    size_t hostStart = 0;
    if (StartsWithNoCase(url, L"ws://")) {
        target.secure = false;
        target.port = 3001;
        hostStart = 5;
    } else if (StartsWithNoCase(url, L"wss://")) {
        target.secure = true;
        target.port = INTERNET_DEFAULT_HTTPS_PORT;
        hostStart = 6;
    } else {
        target.secure = false;
        target.port = 3001;
        hostStart = 0;
    }

    size_t pathStart = url.find(L'/', hostStart);
    std::wstring hostPort = pathStart == std::wstring::npos ? url.substr(hostStart) : url.substr(hostStart, pathStart - hostStart);
    target.path = pathStart == std::wstring::npos ? L"/" : url.substr(pathStart);
    if (target.path.empty()) target.path = L"/";

    size_t colon = hostPort.rfind(L':');
    if (colon != std::wstring::npos && colon + 1 < hostPort.size()) {
        target.host = hostPort.substr(0, colon);
        target.port = static_cast<INTERNET_PORT>(wcstoul(hostPort.c_str() + colon + 1, nullptr, 10));
    } else {
        target.host = hostPort;
    }
    if (target.host.empty()) target.host = L"127.0.0.1";
    if (target.port == 0) target.port = target.secure ? INTERNET_DEFAULT_HTTPS_PORT : 3001;
    return target;
}

static std::wstring ErrorText(DWORD error) {
    wchar_t buf[64]{};
    swprintf(buf, 64, L"错误码 %lu", static_cast<unsigned long>(error));
    return buf;
}

static std::wstring HttpStatusHint(DWORD status) {
    switch (status) {
    case 0: return L"无 HTTP 状态";
    case 101: return L"101 Switching Protocols";
    case 401: return L"401 未授权，Token 可能不对";
    case 403: return L"403 被拒绝，检查 Token/权限";
    case 404: return L"404 路径不对，通常填 / 或 ws://127.0.0.1:3001";
    default: return L"HTTP " + std::to_wstring(status);
    }
}

static bool FetchQqAvatarBytes(const std::wstring& qq, std::vector<BYTE>& bytes) {
    if (qq.empty()) return false;
    HINTERNET session = WinHttpOpen(L"淋雨扣字手/QQAvatar", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) return false;
    WinHttpSetTimeouts(session, 1200, 1500, 1500, 2500);

    HINTERNET connect = WinHttpConnect(session, L"q.qlogo.cn", INTERNET_DEFAULT_HTTP_PORT, 0);
    if (!connect) {
        WinHttpCloseHandle(session);
        return false;
    }

    std::wstring path = L"/headimg_dl?dst_uin=" + qq + L"&spec=640&img_type=png";
    HINTERNET request = WinHttpOpenRequest(connect, L"GET", path.c_str(), nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!request) {
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);
        return false;
    }

    BOOL ok = WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, nullptr, 0, 0, 0)
        && WinHttpReceiveResponse(request, nullptr);
    DWORD status = 0;
    DWORD statusSize = sizeof(status);
    if (ok) {
        WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &status, &statusSize, nullptr);
    }
    std::string body = ok && status == 200 ? WinHttpReadAll(request) : std::string{};

    WinHttpCloseHandle(request);
    WinHttpCloseHandle(connect);
    WinHttpCloseHandle(session);

    if (body.size() < 128) return false;
    const BYTE* first = reinterpret_cast<const BYTE*>(body.data());
    bytes.assign(first, first + body.size());
    return true;
}

static bool IsMentioningSelf(const std::string& json, const std::wstring& raw, const std::wstring& selfId) {
    if (selfId.empty()) return false;
    std::wstring cq = L"qq=" + selfId;
    if (raw.find(cq) != std::wstring::npos) return true;
    std::string id = WideToUtf8(selfId);
    return json.find("\"qq\":" + id) != std::string::npos
        || json.find("\"qq\":\"" + id + "\"") != std::string::npos;
}

static void ProcessNapcatEventJson(const std::string& json, bool onlyAt) {
    std::wstring postType;
    if (!ExtractJsonScalarValue(json, "\"post_type\"", 0, postType) || postType != L"message") return;

    std::wstring messageType;
    ExtractJsonScalarValue(json, "\"message_type\"", 0, messageType);

    std::wstring raw;
    if (!ExtractJsonStringValue(json, "\"raw_message\"", 0, raw)) return;

    std::wstring selfId;
    ExtractJsonScalarValue(json, "\"self_id\"", 0, selfId);
    if (onlyAt && messageType == L"group" && !IsMentioningSelf(json, raw, selfId)) return;

    std::wstring text = StripCqCodes(raw);
    if (text.empty()) return;

    auto* event = new NapcatEvent;
    event->raw = raw;
    event->text = text;
    event->messageType = messageType;
    ExtractJsonScalarValue(json, "\"user_id\"", 0, event->userId);
    ExtractJsonScalarValue(json, "\"group_id\"", 0, event->groupId);

    size_t sender = json.find("\"sender\"");
    std::wstring card;
    if (sender != std::string::npos) {
        ExtractJsonStringValue(json, "\"card\"", sender, card);
        ExtractJsonStringValue(json, "\"nickname\"", sender, event->nickname);
    }
    if (!Trim(card).empty()) event->nickname = card;
    if (Trim(event->nickname).empty()) event->nickname = event->userId;

    PostMessageW(g_app.hwnd, WM_NAPCAT_EVENT, 0, reinterpret_cast<LPARAM>(event));
}

static void NapcatListenThread(std::wstring url, std::wstring token, bool onlyAt) {
    bool failed = false;
    try {
        WsTarget target = ParseWsUrl(url);
        while (g_app.napcatRunning.load()) {
            HINTERNET session = WinHttpOpen(L"淋雨扣字手/NapCat", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
            if (!session) throw std::runtime_error("WinHttpOpen failed");
            WinHttpSetTimeouts(session, 5000, 5000, 5000, 2000);

            HINTERNET connect = WinHttpConnect(session, target.host.c_str(), target.port, 0);
            if (!connect) {
                WinHttpCloseHandle(session);
                throw std::runtime_error("WinHttpConnect failed");
            }

            DWORD flags = target.secure ? WINHTTP_FLAG_SECURE : 0;
            HINTERNET request = WinHttpOpenRequest(connect, L"GET", target.path.c_str(), nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
            if (!request) {
                WinHttpCloseHandle(connect);
                WinHttpCloseHandle(session);
                throw std::runtime_error("WinHttpOpenRequest failed");
            }

            if (!WinHttpSetOption(request, WINHTTP_OPTION_UPGRADE_TO_WEB_SOCKET, nullptr, 0)) {
                DWORD err = GetLastError();
                WinHttpCloseHandle(request);
                WinHttpCloseHandle(connect);
                WinHttpCloseHandle(session);
                throw std::runtime_error("WebSocket upgrade option failed: " + WideToUtf8(ErrorText(err)));
            }

            std::wstring headers;
            if (!Trim(token).empty()) headers = L"Authorization: Bearer " + Trim(token) + L"\r\n";
            BOOL sent = WinHttpSendRequest(request, headers.empty() ? WINHTTP_NO_ADDITIONAL_HEADERS : headers.c_str(),
                headers.empty() ? 0 : static_cast<DWORD>(headers.size()), WINHTTP_NO_REQUEST_DATA, 0, 0, 0);
            if (!sent || !WinHttpReceiveResponse(request, nullptr)) {
                DWORD err = GetLastError();
                WinHttpCloseHandle(request);
                WinHttpCloseHandle(connect);
                WinHttpCloseHandle(session);
                throw std::runtime_error("NapCat WebSocket 连接失败: " + WideToUtf8(ErrorText(err)));
            }

            DWORD status = 0;
            DWORD statusSize = sizeof(status);
            WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &status, &statusSize, nullptr);
            HINTERNET ws = WinHttpWebSocketCompleteUpgrade(request, 0);
            WinHttpCloseHandle(request);
            if (!ws) {
                WinHttpCloseHandle(connect);
                WinHttpCloseHandle(session);
                throw std::runtime_error("WebSocket upgrade failed: " + WideToUtf8(HttpStatusHint(status)));
            }

            PostNapcatStatus(L"NapCat 已连接，正在监听 QQ 新消息。");
            std::string message;
            BYTE buffer[8192]{};
            while (g_app.napcatRunning.load()) {
                DWORD read = 0;
                WINHTTP_WEB_SOCKET_BUFFER_TYPE type{};
                DWORD result = WinHttpWebSocketReceive(ws, buffer, sizeof(buffer), &read, &type);
                if (result == ERROR_WINHTTP_TIMEOUT) continue;
                if (result != ERROR_SUCCESS) {
                    if (g_app.napcatRunning.load()) PostNapcatStatus(L"NapCat 连接断开，准备重连。");
                    break;
                }
                if (type == WINHTTP_WEB_SOCKET_CLOSE_BUFFER_TYPE) {
                    if (g_app.napcatRunning.load()) PostNapcatStatus(L"NapCat 主动断开，准备重连。");
                    break;
                }
                if (read > 0) message.append(reinterpret_cast<char*>(buffer), reinterpret_cast<char*>(buffer) + read);
                if (type == WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE || type == WINHTTP_WEB_SOCKET_BINARY_MESSAGE_BUFFER_TYPE) {
                    ProcessNapcatEventJson(message, onlyAt);
                    message.clear();
                }
            }

            WinHttpWebSocketClose(ws, WINHTTP_WEB_SOCKET_SUCCESS_CLOSE_STATUS, nullptr, 0);
            WinHttpCloseHandle(ws);
            WinHttpCloseHandle(connect);
            WinHttpCloseHandle(session);
            if (!g_app.napcatRunning.load()) break;
            Sleep(1800);
        }
    } catch (const std::exception& ex) {
        failed = true;
        PostNapcatStatus(L"NapCat 监听失败：" + ExceptionMessageToWide(ex));
    }
    g_app.napcatRunning = false;
    if (!failed) PostNapcatStatus(L"NapCat 未监听。");
}

static std::wstring CallDeepSeek(const std::wstring& apiKey, const std::wstring& persona, const std::wstring& prompt) {
    std::wstring systemPrompt = Trim(persona);
    if (systemPrompt.empty()) {
        systemPrompt = L"你是一个自然中文聊天写手，语气像真人聊天，表达清楚但不要太正式。";
    }
    systemPrompt += L"\n只输出要放进聊天框的正文，不要解释，不要 Markdown，不要标题。不要生成辱骂、骚扰、诈骗或违法内容。";

    std::wstring userPrompt = Trim(prompt);
    if (userPrompt.empty()) {
        userPrompt = L"根据这个人设生成一小段适合普通聊天发送的中文文本，长度控制在 1 到 3 句话。";
    }

    std::string body =
        "{"
        "\"model\":\"deepseek-v4-flash\","
        "\"stream\":false,"
        "\"temperature\":0.8,"
        "\"max_tokens\":800,"
        "\"messages\":["
        "{\"role\":\"system\",\"content\":\"" + JsonEscapeUtf8(systemPrompt) + "\"},"
        "{\"role\":\"user\",\"content\":\"" + JsonEscapeUtf8(userPrompt) + "\"}"
        "]"
        "}";

    HINTERNET session = WinHttpOpen(L"淋雨扣字手/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) throw std::runtime_error("WinHttpOpen failed");
    HINTERNET connect = WinHttpConnect(session, L"api.deepseek.com", INTERNET_DEFAULT_HTTPS_PORT, 0);
    if (!connect) {
        WinHttpCloseHandle(session);
        throw std::runtime_error("WinHttpConnect failed");
    }
    HINTERNET request = WinHttpOpenRequest(connect, L"POST", L"/chat/completions", nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    if (!request) {
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);
        throw std::runtime_error("WinHttpOpenRequest failed");
    }

    std::wstring headers = L"Content-Type: application/json\r\nAuthorization: Bearer " + Trim(apiKey) + L"\r\n";
    BOOL sent = WinHttpSendRequest(request, headers.c_str(), static_cast<DWORD>(headers.size()),
        body.data(), static_cast<DWORD>(body.size()), static_cast<DWORD>(body.size()), 0);
    if (!sent || !WinHttpReceiveResponse(request, nullptr)) {
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);
        throw std::runtime_error("DeepSeek request failed");
    }

    DWORD status = 0;
    DWORD statusSize = sizeof(status);
    WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &status, &statusSize, nullptr);
    std::string response = WinHttpReadAll(request);
    WinHttpCloseHandle(request);
    WinHttpCloseHandle(connect);
    WinHttpCloseHandle(session);

    if (status < 200 || status >= 300) {
        std::wstring err;
        if (!ExtractJsonStringValue(response, "\"message\"", 0, err)) err = Utf8ToWide(response);
        throw std::runtime_error("DeepSeek HTTP " + std::to_string(status) + ": " + WideToUtf8(err));
    }
    std::wstring content = Trim(ExtractDeepSeekContent(response));
    if (content.empty()) throw std::runtime_error("DeepSeek returned empty content");
    return content;
}
