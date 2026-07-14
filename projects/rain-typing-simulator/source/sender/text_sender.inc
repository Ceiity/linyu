// 文本分词、拼音转换、SendInput 输入模拟、发送线程与进度声明
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static bool IsCjk(wchar_t ch) {
    return (ch >= 0x3400 && ch <= 0x9FFF) || ch == 0x3007;
}

static std::wstring ToPinyin(const std::wstring& text) {
    std::wstring out;
    for (wchar_t ch : text) {
        if (const wchar_t* py = LookupPinyin(ch)) out += py;
    }
    return out;
}

static bool HasPinyinForEveryCjk(const std::wstring& text) {
    for (wchar_t ch : text) {
        if (IsCjk(ch) && !LookupPinyin(ch)) return false;
    }
    return true;
}

static std::wstring PunctuationKey(wchar_t ch) {
    switch (ch) {
    case L'，': return L",";
    case L'。': return L".";
    case L'！': return L"!";
    case L'？': return L"?";
    case L'；': return L";";
    case L'：': return L":";
    case L'、': return L"\\";
    case L'“': case L'”': return L"\"";
    case L'‘': case L'’': return L"'";
    case L'（': return L"(";
    case L'）': return L")";
    case L'【': return L"[";
    case L'】': return L"]";
    case L'《': return L"<";
    case L'》': return L">";
    case L'－': case L'—': return L"-";
    default: return std::wstring(1, ch);
    }
}

static std::vector<std::wstring> SplitChunks(const std::wstring& text, int chunkMode) {
    std::vector<std::wstring> chunks;
    if (text.empty()) return chunks;
    if (chunkMode == 1) return { text };
    if (chunkMode == 2) {
        for (wchar_t ch : text) chunks.emplace_back(1, ch);
        return chunks;
    }
    std::uniform_int_distribution<int> sizeDist(2, 5);
    std::uniform_real_distribution<double> chance(0.0, 1.0);
    for (size_t i = 0; i < text.size();) {
        size_t n = chance(g_rng) < 0.18 ? 1 : static_cast<size_t>(sizeDist(g_rng));
        chunks.push_back(text.substr(i, std::min(n, text.size() - i)));
        i += n;
    }
    return chunks;
}

static std::vector<std::wstring> SplitLines(std::wstring text) {
    text.erase(std::remove(text.begin(), text.end(), L'\r'), text.end());
    std::vector<std::wstring> lines;
    std::wstringstream ss(text);
    std::wstring line;
    while (std::getline(ss, line, L'\n')) lines.push_back(line);
    if (!text.empty() && text.back() == L'\n') lines.emplace_back();
    if (lines.empty()) lines.emplace_back();
    return lines;
}

static std::wstring PreviewLine(const std::wstring& line, const Settings& settings) {
    std::wstring out;
    std::wstring cjk;
    auto flush = [&] {
        if (cjk.empty()) return;
        for (const auto& chunk : SplitChunks(cjk, settings.chunkMode)) {
            if (settings.inputMode == 0 && settings.correctionEffect) {
                out += ToPinyin(chunk) + L"[删除] ";
                out += chunk + L"[精确上屏] ";
            } else {
                out += ToPinyin(chunk);
                out += settings.inputMode == 0 ? L"[空格候选] " : L"[空格] ";
            }
        }
        cjk.clear();
    };
    for (wchar_t ch : line) {
        if (IsCjk(ch)) {
            cjk.push_back(ch);
        } else {
            flush();
            out += PunctuationKey(ch) + L" ";
        }
    }
    flush();
    return out;
}

static std::wstring BuildPreview(const std::wstring& text, const Settings& settings) {
    auto lines = SplitLines(text);
    std::wstring out;
    if (!settings.inputLayoutName.empty()) out += L"输入法：" + settings.inputLayoutName + L"\r\n";
    if (settings.mentionMode > 0 && !Trim(settings.mentionQq).empty()) {
        const wchar_t* modeText = settings.mentionMode == 1 ? L"（每句）"
            : settings.mentionMode == 2 ? L"（随机）"
            : settings.mentionMode == 3 ? L"（隔几句随机，前后都可能）"
            : L"（直接@，不发送文本）";
        out += L"@提及：@" + Trim(settings.mentionQq) + modeText + L"\r\n";
    }
    size_t maxLines = std::min<size_t>(12, lines.size());
    for (size_t i = 0; i < maxLines; ++i) {
        out += std::to_wstring(i + 1) + L". 原文：" + lines[i] + L"\r\n";
        if (settings.inputMode == 0) {
            if (settings.correctionEffect) {
                out += L"   纠错：" + PreviewLine(lines[i], settings) + L"\r\n";
                out += L"   最终：删除拼音后精确输入预设原文，不靠候选猜词 [回车]\r\n";
            } else {
                out += L"   候选：" + PreviewLine(lines[i], settings) + L"\r\n";
                out += L"   最终：不删除，直接用微软输入法候选上屏 [回车]\r\n";
            }
        } else if (settings.inputMode == 1) {
            out += L"   拼音：" + PreviewLine(lines[i], settings) + L"[回车]\r\n";
        } else {
            out += L"   方式：逐字精确输入，不走候选词 [回车]\r\n";
        }
    }
    if (lines.size() > maxLines) out += L"... 还有 " + std::to_wstring(lines.size() - maxLines) + L" 行\r\n";
    return out;
}

static void SendInputVector(const std::vector<INPUT>& v) {
    if (v.empty()) return;
    for (int attempt = 0; attempt < 3; ++attempt) {
        UINT sent = SendInput(static_cast<UINT>(v.size()), const_cast<INPUT*>(v.data()), sizeof(INPUT));
        if (sent == v.size()) return;
        if (sent > 0) break; // avoid replaying a partially-sent key sequence
        Sleep(6 + attempt * 10);
    }
    throw std::runtime_error("SendInput failed");
}

static void SendInputItems(std::initializer_list<INPUT> items) {
    std::vector<INPUT> v(items);
    SendInputVector(v);
}

static INPUT KeyInput(WORD vk, DWORD flags = 0, WORD scan = 0) {
    INPUT input{};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = vk;
    input.ki.wScan = scan;
    input.ki.dwFlags = flags;
    return input;
}

static void ReleaseModifiers() {
    std::vector<INPUT> inputs;
    const WORD keys[] = { VK_SHIFT, VK_LSHIFT, VK_RSHIFT, VK_CONTROL, VK_LCONTROL, VK_RCONTROL, VK_MENU, VK_LMENU, VK_RMENU, VK_LWIN, VK_RWIN };
    for (WORD vk : keys) {
        if (GetAsyncKeyState(vk) & 0x8000) inputs.push_back(KeyInput(vk, KEYEVENTF_KEYUP));
    }
    SendInputVector(inputs);
}

static void PressVk(WORD vk) {
    SendInputItems({ KeyInput(vk), KeyInput(vk, KEYEVENTF_KEYUP) });
}

static void PressCtrlEnter() {
    SendInputItems({
        KeyInput(VK_CONTROL),
        KeyInput(VK_RETURN),
        KeyInput(VK_RETURN, KEYEVENTF_KEYUP),
        KeyInput(VK_CONTROL, KEYEVENTF_KEYUP),
    });
}

static void TypeUnicode(wchar_t ch) {
    SendInputItems({
        KeyInput(0, KEYEVENTF_UNICODE, static_cast<WORD>(ch)),
        KeyInput(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, static_cast<WORD>(ch)),
    });
}

static void TypePhysical(wchar_t ch) {
    if (ch >= L'a' && ch <= L'z') {
        PressVk(static_cast<WORD>(towupper(ch)));
        return;
    }
    if (ch >= L'A' && ch <= L'Z') {
        SendInputItems({
            KeyInput(VK_SHIFT),
            KeyInput(static_cast<WORD>(ch)),
            KeyInput(static_cast<WORD>(ch), KEYEVENTF_KEYUP),
            KeyInput(VK_SHIFT, KEYEVENTF_KEYUP),
        });
        return;
    }
    if (ch >= L'0' && ch <= L'9') {
        PressVk(static_cast<WORD>(ch));
        return;
    }
    if (ch == L' ') {
        PressVk(VK_SPACE);
        return;
    }

    SHORT code = VkKeyScanW(ch);
    if (code == -1) {
        TypeUnicode(ch);
        return;
    }
    BYTE vk = LOBYTE(code);
    BYTE shift = HIBYTE(code);
    std::vector<INPUT> inputs;
    if (shift & 1) inputs.push_back(KeyInput(VK_SHIFT));
    if (shift & 2) inputs.push_back(KeyInput(VK_CONTROL));
    if (shift & 4) inputs.push_back(KeyInput(VK_MENU));
    inputs.push_back(KeyInput(vk));
    inputs.push_back(KeyInput(vk, KEYEVENTF_KEYUP));
    if (shift & 4) inputs.push_back(KeyInput(VK_MENU, KEYEVENTF_KEYUP));
    if (shift & 2) inputs.push_back(KeyInput(VK_CONTROL, KEYEVENTF_KEYUP));
    if (shift & 1) inputs.push_back(KeyInput(VK_SHIFT, KEYEVENTF_KEYUP));
    SendInputVector(inputs);
}

static std::wstring ProcessNameFromPid(DWORD pid) {
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (!h) return L"";
    wchar_t name[MAX_PATH]{};
    GetModuleBaseNameW(h, nullptr, name, MAX_PATH);
    CloseHandle(h);
    return name;
}

static std::wstring ForegroundProcessName() {
    HWND fg = GetForegroundWindow();
    if (!fg) return L"";
    DWORD pid = 0;
    GetWindowThreadProcessId(fg, &pid);
    return ProcessNameFromPid(pid);
}

static void ApplyInputLayout(HWND target, HKL hkl) {
    if (!target || !hkl) return;
    ReleaseModifiers();
    ActivateKeyboardLayout(hkl, KLF_SETFORPROCESS);
    SendMessageTimeoutW(target, WM_INPUTLANGCHANGEREQUEST, 0, reinterpret_cast<LPARAM>(hkl), SMTO_ABORTIFHUNG, 250, nullptr);
    PostMessageW(target, WM_INPUTLANGCHANGEREQUEST, 0, reinterpret_cast<LPARAM>(hkl));
    Sleep(80);
    if (HIMC imc = ImmGetContext(target)) {
        ImmSetOpenStatus(imc, TRUE);
        ImmReleaseContext(target, imc);
    }
    ReleaseModifiers();
}

static bool IsChineseHkl(HKL hkl) {
    LANGID lang = LOWORD(reinterpret_cast<uintptr_t>(hkl));
    return PRIMARYLANGID(lang) == LANG_CHINESE;
}

static bool IsChineseLayoutName(const std::wstring& name) {
    std::wstring s = name;
    std::transform(s.begin(), s.end(), s.begin(), towlower);
    return s.find(L"中文") != std::wstring::npos
        || s.find(L"chinese") != std::wstring::npos
        || s.find(L"pinyin") != std::wstring::npos
        || s.find(L"搜狗") != std::wstring::npos
        || s.find(L"微软拼音") != std::wstring::npos
        || s.find(L"qq拼音") != std::wstring::npos
        || s.find(L"百度") != std::wstring::npos
        || s.find(L"智能abc") != std::wstring::npos
        || s.find(L"小狼毫") != std::wstring::npos
        || s.find(L"rime") != std::wstring::npos
        || s.find(L"讯飞") != std::wstring::npos;
}

static int FindBestChineseLayoutIndex() {
    int fallback = -1;
    for (size_t i = 0; i < g_inputLayouts.size(); ++i) {
        if (IsChineseHkl(g_inputLayouts[i].hkl)) {
            if (IsChineseLayoutName(g_inputLayouts[i].name)) return static_cast<int>(i);
            if (fallback < 0) fallback = static_cast<int>(i);
        }
    }
    if (fallback >= 0) return fallback;
    for (size_t i = 0; i < g_inputLayouts.size(); ++i) {
        if (IsChineseLayoutName(g_inputLayouts[i].name)) return static_cast<int>(i);
    }
    return -1;
}

static HKL CurrentTargetLayout(HWND target) {
    if (!target) return GetKeyboardLayout(0);
    DWORD tid = GetWindowThreadProcessId(target, nullptr);
    return GetKeyboardLayout(tid ? tid : 0);
}

static HKL ResolveTypingLayout(HWND target, const Settings& settings, std::wstring& resolvedName, bool& autoSwitched) {
    autoSwitched = false;
    HKL current = CurrentTargetLayout(target);
    if (IsChineseHkl(current)) {
        int idx = FindInputLayoutByHkl(current);
        resolvedName = (idx >= 0 && idx < static_cast<int>(g_inputLayouts.size())) ? g_inputLayouts[idx].name : L"当前中文输入法";
        return current;
    }
    int chineseIdx = FindBestChineseLayoutIndex();
    if (chineseIdx >= 0 && chineseIdx < static_cast<int>(g_inputLayouts.size())) {
        autoSwitched = true;
        resolvedName = g_inputLayouts[chineseIdx].name;
        return g_inputLayouts[chineseIdx].hkl;
    }
    resolvedName = settings.inputLayoutName.empty() ? L"当前输入法" : settings.inputLayoutName;
    return settings.inputLayout ? settings.inputLayout : current;
}

static bool IsChatProcessName(std::wstring name) {
    std::transform(name.begin(), name.end(), name.begin(), towlower);
    return name == L"qq.exe" || name == L"ntqq.exe" || name == L"wechat.exe" || name == L"weixin.exe" || name == L"wxwork.exe";
}

static bool IsStopKey() {
    return (GetAsyncKeyState(VK_ESCAPE) & 0x8000) != 0
        || (GetAsyncKeyState(VK_F12) & 0x8000) != 0
        || g_app.stop.load();
}

static bool MouseClickedEdge(bool& left, bool& right, bool& middle) {
    bool l = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
    bool r = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
    bool m = (GetAsyncKeyState(VK_MBUTTON) & 0x8000) != 0;
    bool edge = (l && !left) || (r && !right) || (m && !middle);
    left = l; right = r; middle = m;
    return edge;
}

static void WaitMouseRelease() {
    while ((GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        || (GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        || (GetAsyncKeyState(VK_MBUTTON) & 0x8000)) {
        if (IsStopKey()) return;
        Sleep(15);
    }
}

static void SleepKey(const Settings& settings) {
    double delay = settings.keyDelay;
    if (settings.humanize) {
        std::uniform_real_distribution<double> scale(0.55, 1.75);
        delay *= scale(g_rng);
        std::uniform_real_distribution<double> chance(0.0, 1.0);
        if (chance(g_rng) < settings.pauseChance) {
            std::uniform_real_distribution<double> pause(settings.pauseMin, settings.pauseMax);
            delay += pause(g_rng);
        }
    }
    delay = std::max(delay, 0.004);
    Sleep(std::max<DWORD>(1, static_cast<DWORD>(delay * 1000)));
}

static void SleepCommit(const Settings& settings) {
    double delay = settings.commitDelay;
    if (settings.humanize) {
        std::uniform_real_distribution<double> scale(0.75, 1.65);
        delay *= scale(g_rng);
    }
    Sleep(static_cast<DWORD>(delay * 1000));
}

struct SendContext {
    Settings settings;
    bool l = false;
    bool r = false;
    bool m = false;
    bool sending = false;

    bool ShouldStop() {
        if (IsStopKey()) return true;
        if (sending && MouseClickedEdge(l, r, m)) {
            g_app.stop = true;
            SetStatus(L"已停止：发送过程中检测到鼠标点击。");
            return true;
        }
        return false;
    }
};

static void TypeLetters(const std::wstring& text, SendContext& ctx) {
    ReleaseModifiers();
    for (wchar_t ch : text) {
        if (ctx.ShouldStop()) return;
        TypePhysical(ch);
        PlayKeySound(ctx.settings);
        SleepKey(ctx.settings);
    }
}

static void TypeFullLetters(const std::wstring& text, SendContext& ctx) {
    ReleaseModifiers();
    for (wchar_t ch : text) {
        if (ctx.ShouldStop()) return;
        if ((ch >= L'a' && ch <= L'z') || (ch >= L'A' && ch <= L'Z')) {
            PressVk(static_cast<WORD>(towupper(ch)));
        } else if (ch >= L'0' && ch <= L'9') {
            PressVk(static_cast<WORD>(ch));
        } else if (ch == L' ') {
            PressVk(VK_SPACE);
        } else {
            TypePhysical(ch);
        }
        PlayKeySound(ctx.settings);
        SleepKey(ctx.settings);
    }
}

static void TypeExact(const std::wstring& text, SendContext& ctx) {
    for (wchar_t ch : text) {
        if (ctx.ShouldStop()) return;
        TypeUnicode(ch);
        PlayKeySound(ctx.settings);
        SleepKey(ctx.settings);
    }
}

static void BackspaceCount(size_t count, SendContext& ctx) {
    for (size_t i = 0; i < count; ++i) {
        if (ctx.ShouldStop()) return;
        PressVk(VK_BACK);
        PlayKeySound(ctx.settings);
        Sleep(ctx.settings.humanize ? 12 : 8);
    }
}

static void TypeChinese(const std::wstring& text, SendContext& ctx) {
    for (const auto& chunk : SplitChunks(text, ctx.settings.chunkMode)) {
        if (ctx.ShouldStop()) return;
        auto py = ToPinyin(chunk);
        if (py.empty() || !HasPinyinForEveryCjk(chunk)) {
            TypeExact(chunk, ctx);
            continue;
        }
        if (ctx.settings.inputMode == 0) {
            if (ctx.settings.correctionEffect) {
                TypeFullLetters(py, ctx);
                SleepCommit(ctx.settings);
                BackspaceCount(py.size(), ctx);
                TypeExact(chunk, ctx);
                continue;
            }
            TypeFullLetters(py, ctx);
            SleepCommit(ctx.settings);
            PressVk(VK_SPACE);
            PlayKeySound(ctx.settings);
            SleepCommit(ctx.settings);
        } else {
            TypeFullLetters(py, ctx);
            SleepCommit(ctx.settings);
            PressVk(VK_SPACE);
            PlayKeySound(ctx.settings);
            SleepCommit(ctx.settings);
        }
    }
}

static void TypeLine(const std::wstring& line, SendContext& ctx) {
    if (ctx.settings.inputMode == 2) {
        TypeExact(line, ctx);
        return;
    }
    std::wstring cjk;
    auto flush = [&] {
        if (!cjk.empty()) {
            TypeChinese(cjk, ctx);
            cjk.clear();
        }
    };
    for (wchar_t ch : line) {
        if (ctx.ShouldStop()) return;
        if (IsCjk(ch)) {
            cjk.push_back(ch);
            continue;
        }
        flush();
        if (ctx.settings.inputMode == 0 && ctx.settings.correctionEffect) {
            TypeExact(std::wstring(1, ch), ctx);
        } else {
            TypeLetters(PunctuationKey(ch), ctx);
        }
    }
    flush();
}

static bool ShouldMentionLine(const Settings& settings) {
    if (settings.mentionMode <= 0 || Trim(settings.mentionQq).empty()) return false;
    if (settings.mentionMode == 1) return true;
    if (settings.mentionMode >= 3) return false;
    std::uniform_real_distribution<double> chance(0.0, 1.0);
    return chance(g_rng) < 0.45;
}

static void TypeMentionPrefix(SendContext& ctx, bool hasTextAfterMention) {
    std::wstring qq = Trim(ctx.settings.mentionQq);
    if (qq.empty()) return;
    TypeLetters(L"@" + qq, ctx);
    if (ctx.ShouldStop()) return;
    SleepCommit(ctx.settings);
    PressVk(VK_RETURN);
    PlayKeySound(ctx.settings);
    SleepCommit(ctx.settings);
    if (hasTextAfterMention) {
        PressVk(VK_SPACE);
        PlayKeySound(ctx.settings);
        SleepKey(ctx.settings);
    }
}

static void SendEnter(SendContext& ctx) {
    if (ctx.settings.enterMode == 0) {
        PressVk(VK_RETURN);
        PlayKeySound(ctx.settings);
    } else if (ctx.settings.enterMode == 1) {
        PressCtrlEnter();
        PlayKeySound(ctx.settings);
    }
}

static void WriteSendProgress(const std::wstring& path, size_t nextLine);
static size_t ReadSendProgress(const std::wstring& path, size_t lineCount);
static void ResetSendProgressForPath(const std::wstring& path);

static void SendThread(std::wstring text, Settings settings, std::wstring sourcePath, size_t startLine) {
    try {
    g_app.running = true;
    g_app.stop = false;
    SendContext ctx;
    ctx.settings = settings;

    bool l = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
    bool r = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
    bool m = (GetAsyncKeyState(VK_MBUTTON) & 0x8000) != 0;

    SetStatus(settings.checkForeground
        ? L"已就绪：请点击 QQ/微信聊天输入框，点中后立即开始。"
        : L"已就绪：请点击目标输入框，点中后立即开始。");

    while (true) {
        if (IsStopKey()) {
            SetStatus(L"已停止。");
            g_app.running = false;
            return;
        }
        if (MouseClickedEdge(l, r, m)) {
            Sleep(90);
            auto fg = ForegroundProcessName();
            if (!settings.checkForeground || IsChatProcessName(fg)) {
                SetStatus(L"已确认聊天框，马上开始。发送中点击鼠标或按 F12 停止。");
                WaitMouseRelease();
                HWND target = GetForegroundWindow();
                std::wstring layoutName;
                bool autoSwitched = false;
                HKL typingLayout = ResolveTypingLayout(target, settings, layoutName, autoSwitched);
                ApplyInputLayout(target, typingLayout);
                if (!layoutName.empty()) {
                    SetStatus((autoSwitched ? L"检测到英文输入法，已自动切到中文：" : L"已检测并启用输入法：") + layoutName + L"。马上开始。");
                }
                Sleep(180);
                break;
            }
            SetStatus(L"点到的不是 QQ/微信，继续等待聊天输入框。当前：" + (fg.empty() ? L"未知" : fg));
        }
        Sleep(20);
    }

    ctx.l = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
    ctx.r = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
    ctx.m = (GetAsyncKeyState(VK_MBUTTON) & 0x8000) != 0;
    ctx.sending = true;

    auto lines = SplitLines(text);
    if (startLine >= lines.size()) startLine = 0;
    std::uniform_int_distribution<int> mentionGap(2, 5);
    std::uniform_real_distribution<double> mentionSide(0.0, 1.0);
    size_t nextNaturalMention = static_cast<size_t>(mentionGap(g_rng) - 1);
    for (size_t i = startLine; i < lines.size(); ++i) {
        if (ctx.ShouldStop()) {
            g_app.running = false;
            return;
        }
        SetStatus(L"正在发送第 " + std::to_wstring(i + 1) + L"/" + std::to_wstring(lines.size()) + L" 行。点击鼠标或按 F12 停止。");

        if (settings.mentionMode == 4 && !Trim(settings.mentionQq).empty()) {
            TypeMentionPrefix(ctx, false);
            if (ctx.ShouldStop()) {
                g_app.running = false;
                return;
            }
            SendEnter(ctx);
            WriteSendProgress(sourcePath, i + 1);
            Sleep(static_cast<DWORD>(settings.lineDelay * 1000));
            continue;
        }

        bool mentioned = false;
        bool mentionBefore = ShouldMentionLine(settings);
        bool mentionAfter = false;
        if (settings.mentionMode == 3 && !Trim(settings.mentionQq).empty() && i >= nextNaturalMention) {
            if (!Trim(lines[i]).empty() && mentionSide(g_rng) < 0.5) mentionAfter = true;
            else mentionBefore = true;
            nextNaturalMention = i + static_cast<size_t>(mentionGap(g_rng));
        }
        if (mentionBefore) {
            mentioned = true;
            TypeMentionPrefix(ctx, !Trim(lines[i]).empty());
            if (ctx.ShouldStop()) {
                g_app.running = false;
                return;
            }
        }
        TypeLine(lines[i], ctx);
        if (ctx.ShouldStop()) {
            g_app.running = false;
            return;
        }
        if (mentionAfter) {
            mentioned = true;
            TypeLetters(L" ", ctx);
            TypeMentionPrefix(ctx, false);
            if (ctx.ShouldStop()) {
                g_app.running = false;
                return;
            }
        }
        if (i + 1 != lines.size() || !lines[i].empty() || mentioned) SendEnter(ctx);
        WriteSendProgress(sourcePath, i + 1);
        Sleep(static_cast<DWORD>(settings.lineDelay * 1000));
    }

    WriteSendProgress(sourcePath, 0);
    SetStatus(L"发送完成。");
    g_app.running = false;
    } catch (const std::exception& ex) {
        g_app.running = false;
        g_app.stop = true;
        SetStatus(L"已停止：输入接口短暂失败，请重新点开始。");
    } catch (...) {
        g_app.running = false;
        g_app.stop = true;
        SetStatus(L"已停止：发送时遇到未知错误，请重新点开始。");
    }
}
