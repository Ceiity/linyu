// AI 生成文件路径、DeepSeek 提示词构造、生成结果保存与启动发送
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static std::wstring AiGeneratedPath() {
    return ConfigDir() + L"\\ai_generated.txt";
}

static std::wstring ExceptionMessageToWide(const std::exception& ex) {
    std::string what = ex.what() ? ex.what() : "";
    std::wstring msg = Utf8ToWide(what);
    return msg.empty() && !what.empty() ? AcpToWide(what) : msg;
}

static bool HasFreshNapcatMessage() {
    if (Trim(g_app.lastNapcatText).empty()) return false;
    ULONGLONG now = GetTickCount64();
    return g_app.lastNapcatTick != 0 && now >= g_app.lastNapcatTick && now - g_app.lastNapcatTick <= 10ull * 60ull * 1000ull;
}

static std::wstring BuildAiRequestPrompt(std::wstring prompt, int count) {
    std::wstring requestPrompt = Trim(prompt);
    if (g_app.napcatUseContextChecked && HasFreshNapcatMessage()) {
        std::wstring context;
        context += L"对方昵称：" + (Trim(g_app.lastNapcatName).empty() ? L"未知" : Trim(g_app.lastNapcatName)) + L"\n";
        context += L"对方QQ：" + (Trim(g_app.lastNapcatUserId).empty() ? L"未知" : Trim(g_app.lastNapcatUserId)) + L"\n";
        if (!Trim(g_app.lastNapcatGroupId).empty()) context += L"群号：" + Trim(g_app.lastNapcatGroupId) + L"\n";
        context += L"对方原话：\n" + Trim(g_app.lastNapcatText) + L"\n\n";
        if (requestPrompt.empty()) {
            requestPrompt = context + L"请根据对方这句话生成自然中文回复。";
        } else {
            requestPrompt = context + L"我的额外要求：\n" + requestPrompt;
        }
    } else if (requestPrompt.empty()) {
        requestPrompt = L"生成适合普通聊天发送的自然中文回复。";
    }
    requestPrompt += L"\n\n请一次生成 " + std::to_wstring(count)
        + L" 句可以连续发送的短句。每句单独一行，不要编号，不要解释。语气自然，像真人现场聊天；可以反驳但不要辱骂、人身攻击、威胁、骚扰。";
    return requestPrompt;
}

static std::wstring StripGeneratedLinePrefix(std::wstring line) {
    line = Trim(line);
    size_t i = 0;
    while (i < line.size() && iswdigit(line[i])) ++i;
    if (i > 0 && i < line.size() && (line[i] == L'.' || line[i] == L'、' || line[i] == L')' || line[i] == L'）')) {
        line = Trim(line.substr(i + 1));
    }
    if (!line.empty() && (line[0] == L'-' || line[0] == L'*' || line[0] == L'•')) {
        line = Trim(line.substr(1));
    }
    return line;
}

static std::wstring NormalizeAiGeneratedText(std::wstring content, int count) {
    auto lines = SplitLines(content);
    std::vector<std::wstring> clean;
    for (auto& line : lines) {
        auto trimmed = StripGeneratedLinePrefix(line);
        if (!trimmed.empty()) clean.push_back(trimmed);
    }
    if (clean.empty()) return Trim(content);
    if (count > 0 && clean.size() > static_cast<size_t>(count)) clean.resize(count);
    std::wstring out;
    for (size_t i = 0; i < clean.size(); ++i) {
        if (i) out += L"\r\n";
        out += clean[i];
    }
    return out;
}

static void GenerateAiText(bool startAfterDone = false) {
    if (g_app.aiGenerating.exchange(true)) {
        MessageBoxW(g_app.hwnd, L"AI 正在生成中。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
        return;
    }
    std::wstring apiKey = Trim(GetWindowTextString(g_app.aiApiKeyEdit));
    if (apiKey.empty()) {
        g_app.aiGenerating = false;
        MessageBoxW(g_app.hwnd, L"请先填写 DeepSeek API Key；不填也可以继续用 txt 文件发送。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
        return;
    }
    std::wstring persona = GetWindowTextString(g_app.aiPersonaEdit);
    std::wstring prompt = GetWindowTextString(g_app.aiPromptEdit);
    int count = std::clamp(ReadInt(g_app.aiCountEdit, 10), 1, 10);
    SetWindowTextW(g_app.aiCountEdit, std::to_wstring(count).c_str());
    std::wstring requestPrompt = BuildAiRequestPrompt(prompt, count);
    g_app.aiStartAfterDone = startAfterDone;
    SaveConfig();
    SetWindowTextW(g_app.status, HasFreshNapcatMessage() && g_app.napcatUseContextChecked
        ? L"AI 正在根据 NapCat 最新消息生成回复。"
        : L"AI 正在生成文本，请稍等。");
    std::thread([apiKey, persona, requestPrompt, count]() {
        try {
            std::wstring content = NormalizeAiGeneratedText(CallDeepSeek(apiKey, persona, requestPrompt), count);
            std::wstring path = AiGeneratedPath();
            WriteUtf8BomFile(path, content);
            PostMessageW(g_app.hwnd, WM_AI_DONE, 0, reinterpret_cast<LPARAM>(new std::wstring(path)));
        } catch (const std::exception& ex) {
            PostMessageW(g_app.hwnd, WM_AI_FAILED, 0, reinterpret_cast<LPARAM>(new std::wstring(ExceptionMessageToWide(ex))));
        }
    }).detach();
}

static void StartAiOrPreset() {
    if (g_app.running.load()) {
        MessageBoxW(g_app.hwnd, L"正在发送中。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
        return;
    }
    if (g_app.napcatUseContextChecked && !HasFreshNapcatMessage()) {
        SetWindowTextW(g_app.status, L"没有检测到 10 分钟内的新消息，改用预设文本。");
        StartSending();
        return;
    }
    GenerateAiText(true);
}
