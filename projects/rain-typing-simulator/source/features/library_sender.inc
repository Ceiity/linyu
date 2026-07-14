// 开始发送、文件选择、发送进度、词库管理、词库弹窗、QQ 头像预览请求
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static bool ConfirmPreview(HWND parent, const std::wstring& preview) {
    return MessageBoxW(parent, (preview + L"\r\n确认发送？").c_str(), L"发送前预览", MB_ICONINFORMATION | MB_OKCANCEL) == IDOK;
}

static void SaveConfig();
static void UpdateLibraryButtonText();

static void StartSending(bool resumeProgress = false) {
    if (g_app.running.load()) {
        MessageBoxW(g_app.hwnd, L"正在发送中。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
        return;
    }
    auto path = GetWindowTextString(g_app.pathEdit);
    if (path.empty() || GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(g_app.hwnd, L"请选择一个存在的 txt 文件。", APP_TITLE, MB_OK | MB_ICONERROR);
        return;
    }
    auto text = ReadTextFile(path);
    if (text.empty()) {
        if (MessageBoxW(g_app.hwnd, L"文件为空或读取失败，仍然继续？", APP_TITLE, MB_YESNO | MB_ICONQUESTION) != IDYES) return;
    }
    Settings settings = ReadSettings();
    SaveConfig();
    if (settings.previewBefore) {
        if (!ConfirmPreview(g_app.hwnd, BuildPreview(text, settings))) return;
    }
    auto lines = SplitLines(text);
    size_t startLine = resumeProgress ? ReadSendProgress(path, lines.size()) : 0;
    if (!resumeProgress) WriteSendProgress(path, 0);
    if (resumeProgress && startLine >= lines.size()) startLine = 0;
    if (resumeProgress && startLine > 0) {
        SetWindowTextW(g_app.status, (L"继续发送：将从第 " + std::to_wstring(startLine + 1) + L" 行开始。").c_str());
    }
    std::thread(SendThread, text, settings, path, startLine).detach();
}

static bool PickTextFileForOwner(HWND owner, std::wstring& file) {
    OPENFILENAMEW ofn{};
    wchar_t buffer[MAX_PATH]{};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner = owner ? owner : g_app.hwnd;
    ofn.lpstrFilter = L"Text files\0*.txt\0All files\0*.*\0";
    ofn.lpstrFile = buffer;
    ofn.nMaxFile = MAX_PATH;
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST;
    if (GetOpenFileNameW(&ofn)) {
        file = buffer;
        return true;
    }
    return false;
}

static bool PickTextFile(std::wstring& file) {
    return PickTextFileForOwner(g_app.hwnd, file);
}

static uint64_t HashProgressPath(const std::wstring& path) {
    uint64_t hash = 1469598103934665603ull;
    for (wchar_t ch : path) {
        wchar_t normalized = ch == L'/' ? L'\\' : towlower(ch);
        hash ^= static_cast<uint64_t>(normalized);
        hash *= 1099511628211ull;
    }
    return hash;
}

static std::wstring ProgressKeyForPath(const std::wstring& path) {
    return L"p_" + std::to_wstring(HashProgressPath(path));
}

static size_t ReadSendProgress(const std::wstring& path, size_t lineCount) {
    if (path.empty() || lineCount == 0) return 0;
    int value = GetPrivateProfileIntW(L"progress", ProgressKeyForPath(path).c_str(), 0, ConfigPath().c_str());
    if (value < 0) value = 0;
    return std::min(static_cast<size_t>(value), lineCount);
}

static void WriteSendProgress(const std::wstring& path, size_t nextLine) {
    if (path.empty()) return;
    WritePrivateProfileStringW(L"progress", ProgressKeyForPath(path).c_str(), std::to_wstring(nextLine).c_str(), ConfigPath().c_str());
}

static void ResetSendProgressForPath(const std::wstring& path) {
    if (path.empty()) return;
    WriteSendProgress(path, 0);
}

static void BrowseFile() {
    std::wstring file;
    if (PickTextFile(file)) {
        g_app.librarySel = -1;
        SetWindowTextW(g_app.pathEdit, file.c_str());
        UpdateLibraryButtonText();
        SetWindowTextW(g_app.status, L"已载入文本。需要常用的话可以点“添加词库”。");
        SaveConfig();
    }
}

static std::wstring TextLibraryConfigPath() {
    return ConfigDir() + L"\\text_libraries.ini";
}

static std::wstring TextLibraryStoreDir() {
    std::wstring dir = ConfigDir() + L"\\TextLibraries";
    CreateDirectoryW(dir.c_str(), nullptr);
    return dir;
}

static std::wstring FileNameOnly(const std::wstring& path) {
    size_t pos = path.find_last_of(L"\\/");
    return pos == std::wstring::npos ? path : path.substr(pos + 1);
}

static std::wstring RemoveExtension(std::wstring name) {
    size_t dot = name.find_last_of(L'.');
    if (dot != std::wstring::npos && dot > 0) name = name.substr(0, dot);
    return name;
}

static std::wstring CleanLibraryName(std::wstring name) {
    name = Trim(name);
    if (name.empty()) name = L"未命名词库";
    const std::wstring bad = L"\\/:*?\"<>|";
    for (wchar_t& ch : name) {
        if (bad.find(ch) != std::wstring::npos || ch < 32) ch = L'_';
    }
    if (name.size() > 48) name.resize(48);
    return name;
}

static std::wstring UniqueLibraryPath(const std::wstring& name) {
    std::wstring base = CleanLibraryName(name);
    std::wstring dir = TextLibraryStoreDir();
    std::wstring path = dir + L"\\" + base + L".txt";
    for (int i = 2; GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES; ++i) {
        path = dir + L"\\" + base + L"_" + std::to_wstring(i) + L".txt";
    }
    return path;
}

static void UpdateLibraryButtonText() {
    if (!g_app.librarySelect) return;
    std::wstring text = L"选择词库  ▾";
    if (g_app.librarySel >= 0 && g_app.librarySel < static_cast<int>(g_textLibraries.size())) {
        text = L"词库：" + ShortText(g_textLibraries[g_app.librarySel].name, 18) + L"  ▾";
    }
    SetWindowTextW(g_app.librarySelect, text.c_str());
    InvalidateRect(g_app.librarySelect, nullptr, TRUE);
}

static void SaveTextLibraries() {
    std::wstring cfg = TextLibraryConfigPath();
    WritePrivateProfileStringW(L"libraries", L"count", std::to_wstring(g_textLibraries.size()).c_str(), cfg.c_str());
    for (size_t i = 0; i < g_textLibraries.size(); ++i) {
        std::wstring section = L"library_" + std::to_wstring(i);
        WritePrivateProfileStringW(section.c_str(), L"name", g_textLibraries[i].name.c_str(), cfg.c_str());
        WritePrivateProfileStringW(section.c_str(), L"path", g_textLibraries[i].path.c_str(), cfg.c_str());
    }
}

static void LoadTextLibraries() {
    g_textLibraries.clear();
    std::wstring cfg = TextLibraryConfigPath();
    int count = GetPrivateProfileIntW(L"libraries", L"count", 0, cfg.c_str());
    for (int i = 0; i < count; ++i) {
        std::wstring section = L"library_" + std::to_wstring(i);
        wchar_t name[256]{};
        wchar_t path[MAX_PATH]{};
        GetPrivateProfileStringW(section.c_str(), L"name", L"", name, 256, cfg.c_str());
        GetPrivateProfileStringW(section.c_str(), L"path", L"", path, MAX_PATH, cfg.c_str());
        if (path[0]) g_textLibraries.push_back({ CleanLibraryName(name), path });
    }
}

static void SelectTextLibrary(int index) {
    if (index < 0 || index >= static_cast<int>(g_textLibraries.size())) return;
    g_app.librarySel = index;
    SetWindowTextW(g_app.pathEdit, g_textLibraries[index].path.c_str());
    UpdateLibraryButtonText();
    SetWindowTextW(g_app.status, (L"已选择词库：" + g_textLibraries[index].name).c_str());
    SaveConfig();
}

struct PromptState {
    std::wstring prompt;
    std::wstring initial;
    std::wstring value;
    HWND edit{};
    bool done = false;
    bool ok = false;
};

static void DrawOwnerButton(const DRAWITEMSTRUCT* item);

static LRESULT CALLBACK PromptWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    auto* state = reinterpret_cast<PromptState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    switch (msg) {
    case WM_CREATE: {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        state = reinterpret_cast<PromptState*>(cs->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));
        state->edit = CreateWindowExW(0, L"EDIT", state->initial.c_str(),
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 42, 92, 326, 26, hwnd, (HMENU)10, nullptr, nullptr);
        HWND ok = CreateWindowW(L"BUTTON", L"保存词库", WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
            78, 150, 126, 36, hwnd, (HMENU)IDOK, nullptr, nullptr);
        HWND cancel = CreateWindowW(L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
            222, 150, 112, 36, hwnd, (HMENU)IDCANCEL, nullptr, nullptr);
        HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        SendMessageW(state->edit, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(ok, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(cancel, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(state->edit, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
        SetFocus(state->edit);
        SendMessageW(state->edit, EM_SETSEL, 0, -1);
        return 0;
    }
    case WM_COMMAND:
        if (LOWORD(wParam) == IDOK) {
            state->value = GetWindowTextString(state->edit);
            state->ok = true;
            state->done = true;
            DestroyWindow(hwnd);
            return 0;
        }
        if (LOWORD(wParam) == IDCANCEL) {
            state->done = true;
            DestroyWindow(hwnd);
            return 0;
        }
        break;
    case WM_CLOSE:
        if (state) state->done = true;
        DestroyWindow(hwnd);
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(hwnd, &ps);
        RECT client{};
        GetClientRect(hwnd, &client);
        HBRUSH bg = CreateSolidBrush(C_BG);
        FillRect(dc, &client, bg);
        DeleteObject(bg);
        DrawRoundPanel(dc, { 16, 16, client.right - 16, client.bottom - 16 }, C_CARD, C_BORDER, 22);
        DrawRoundPanel(dc, { 34, 82, client.right - 34, 124 }, C_CONTROL, C_BORDER, 14);
        SetBkMode(dc, TRANSPARENT);
        HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        HGDIOBJ oldFont = SelectObject(dc, font);
        RECT title{ 34, 34, client.right - 34, 60 };
        RECT hint{ 34, 58, client.right - 34, 80 };
        SetTextColor(dc, C_TEXT);
        std::wstring prompt = state ? state->prompt : L"给这个词库取个名字";
        DrawTextW(dc, prompt.c_str(), -1, &title, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SetTextColor(dc, C_MUTED);
        DrawTextW(dc, L"保存后可在词库下拉里直接选择", -1, &hint, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, oldFont);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_DRAWITEM:
        DrawOwnerButton(reinterpret_cast<DRAWITEMSTRUCT*>(lParam));
        return TRUE;
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)wParam;
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, C_TEXT);
        return (LRESULT)g_cardBrush;
    }
    case WM_CTLCOLOREDIT: {
        HDC dc = (HDC)wParam;
        SetTextColor(dc, C_TEXT);
        SetBkColor(dc, C_CONTROL);
        return (LRESULT)g_controlBrush;
    }
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static bool PromptText(HWND parent, const std::wstring& title, const std::wstring& prompt,
    const std::wstring& initial, std::wstring& value) {
    HINSTANCE hinst = (HINSTANCE)GetModuleHandleW(nullptr);
    static bool registered = false;
    if (!registered) {
        WNDCLASSW wc{};
        wc.lpfnWndProc = PromptWndProc;
        wc.hInstance = hinst;
        wc.lpszClassName = L"LinyuKouziPrompt";
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
        RegisterClassW(&wc);
        registered = true;
    }

    RECT pr{};
    GetWindowRect(parent, &pr);
    int w = 430, h = 240;
    int x = pr.left + ((pr.right - pr.left) - w) / 2;
    int y = pr.top + ((pr.bottom - pr.top) - h) / 2;
    PromptState state{ prompt, initial };
    EnableWindow(parent, FALSE);
    HWND dlg = CreateWindowExW(WS_EX_DLGMODALFRAME, L"LinyuKouziPrompt", title.c_str(),
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, x, y, w, h, parent, nullptr, hinst, &state);
    ShowWindow(dlg, SW_SHOW);
    UpdateWindow(dlg);
    MSG msg{};
    while (!state.done && GetMessageW(&msg, nullptr, 0, 0) > 0) {
        if (!IsDialogMessageW(dlg, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    EnableWindow(parent, TRUE);
    SetForegroundWindow(parent);
    if (state.ok) {
        value = state.value;
        return true;
    }
    return false;
}

static void AddTextLibraryFromFile(const std::wstring& file, std::wstring name) {
    std::wstring text = ReadTextFile(file);
    if (text.empty()) {
        if (MessageBoxW(g_app.hwnd, L"这个文本为空或读取失败，仍然添加到词库？", APP_TITLE, MB_YESNO | MB_ICONQUESTION) != IDYES) {
            return;
        }
    }
    if (Trim(name).empty()) name = RemoveExtension(FileNameOnly(file));
    name = CleanLibraryName(name);
    std::wstring stored = UniqueLibraryPath(name);
    try {
        WriteUtf8BomFile(stored, text);
    } catch (const std::exception& ex) {
        MessageBoxW(g_app.hwnd, (L"保存词库失败：" + ExceptionMessageToWide(ex)).c_str(), APP_TITLE, MB_OK | MB_ICONERROR);
        return;
    }
    g_textLibraries.push_back({ name, stored });
    g_app.librarySel = static_cast<int>(g_textLibraries.size()) - 1;
    SetWindowTextW(g_app.pathEdit, stored.c_str());
    SaveTextLibraries();
    UpdateLibraryButtonText();
    SaveConfig();
    SetWindowTextW(g_app.status, (L"已添加词库：" + name).c_str());
}

struct LibraryDropState {
    bool done = false;
    bool ok = false;
    std::wstring file;
    std::wstring name;
    HWND nameEdit{};
};

static void DrawOwnerButton(const DRAWITEMSTRUCT* item);

static LRESULT CALLBACK LibraryDropWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    auto* state = reinterpret_cast<LibraryDropState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    switch (msg) {
    case WM_CREATE: {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lParam);
        state = reinterpret_cast<LibraryDropState*>(cs->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));
        DragAcceptFiles(hwnd, TRUE);
        HWND nameLabel = CreateWindowW(L"STATIC", L"给这个词库取个名字", WS_CHILD | WS_VISIBLE,
            46, 156, 180, 22, hwnd, nullptr, nullptr, nullptr);
        state->nameEdit = CreateWindowExW(0, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 46, 184, 358, 26, hwnd, nullptr, nullptr, nullptr);
        HWND choose = CreateWindowW(L"BUTTON", L"选择 txt", WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
            46, 238, 112, 36, hwnd, (HMENU)ID_LIBRARY_DROP_SELECT, nullptr, nullptr);
        HWND save = CreateWindowW(L"BUTTON", L"保存词库", WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
            170, 238, 112, 36, hwnd, (HMENU)IDOK, nullptr, nullptr);
        HWND cancel = CreateWindowW(L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
            294, 238, 112, 36, hwnd, (HMENU)IDCANCEL, nullptr, nullptr);
        HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        SendMessageW(nameLabel, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(state->nameEdit, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(state->nameEdit, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
        SendMessageW(choose, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(save, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(cancel, WM_SETFONT, (WPARAM)font, TRUE);
        return 0;
    }
    case WM_DROPFILES: {
        HDROP drop = (HDROP)wParam;
        wchar_t file[MAX_PATH]{};
        if (DragQueryFileW(drop, 0, file, MAX_PATH) && state) {
            state->file = file;
            SetWindowTextW(state->nameEdit, CleanLibraryName(RemoveExtension(FileNameOnly(file))).c_str());
            InvalidateRect(hwnd, nullptr, TRUE);
        }
        DragFinish(drop);
        return 0;
    }
    case WM_COMMAND:
        if (LOWORD(wParam) == ID_LIBRARY_DROP_SELECT) {
            std::wstring file;
            if (PickTextFileForOwner(hwnd, file) && state) {
                state->file = file;
                SetWindowTextW(state->nameEdit, CleanLibraryName(RemoveExtension(FileNameOnly(file))).c_str());
                InvalidateRect(hwnd, nullptr, TRUE);
            }
            return 0;
        }
        if (LOWORD(wParam) == IDOK) {
            if (!state || state->file.empty()) {
                MessageBoxW(hwnd, L"先拖入一个 txt，或点“选择 txt”。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
                return 0;
            }
            state->name = GetWindowTextString(state->nameEdit);
            state->ok = true;
            state->done = true;
            DestroyWindow(hwnd);
            return 0;
        }
        if (LOWORD(wParam) == IDCANCEL) {
            if (state) state->done = true;
            DestroyWindow(hwnd);
            return 0;
        }
        break;
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(hwnd, &ps);
        RECT client{};
        GetClientRect(hwnd, &client);
        HBRUSH bg = CreateSolidBrush(C_BG);
        FillRect(dc, &client, bg);
        DeleteObject(bg);
        DrawRoundPanel(dc, { 16, 16, client.right - 16, client.bottom - 16 }, C_CARD, C_BORDER, 22);
        RECT drop{ 34, 42, client.right - 34, 142 };
        DrawRoundPanel(dc, drop, C_CONTROL, C_BORDER, 18);
        RECT title{ drop.left + 12, drop.top + 16, drop.right - 12, drop.top + 42 };
        RECT hint{ drop.left + 12, drop.top + 48, drop.right - 12, drop.bottom - 12 };
        DrawRoundPanel(dc, { 34, 178, client.right - 34, 220 }, C_CONTROL, C_BORDER, 14);
        SetBkMode(dc, TRANSPARENT);
        HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        HGDIOBJ oldFont = SelectObject(dc, font);
        SetTextColor(dc, C_TEXT);
        std::wstring main = (state && !state->file.empty()) ? L"已选择：" + ShortText(FileNameOnly(state->file), 28) : L"拖入 txt 添加到词库";
        DrawTextW(dc, main.c_str(), -1, &title, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SetTextColor(dc, C_MUTED);
        DrawTextW(dc, state && !state->file.empty() ? L"确认名字后保存到词库" : L"也可以点下面按钮选择文本文件", -1, &hint, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, oldFont);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_DRAWITEM:
        DrawOwnerButton(reinterpret_cast<DRAWITEMSTRUCT*>(lParam));
        return TRUE;
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)wParam;
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, C_TEXT);
        return (LRESULT)g_cardBrush;
    }
    case WM_CTLCOLOREDIT: {
        HDC dc = (HDC)wParam;
        SetTextColor(dc, C_TEXT);
        SetBkColor(dc, C_CONTROL);
        return (LRESULT)g_controlBrush;
    }
    case WM_CLOSE:
        if (state) state->done = true;
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        DragAcceptFiles(hwnd, FALSE);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static bool ShowLibraryDropDialog(HWND parent, std::wstring& file, std::wstring& name) {
    HINSTANCE hinst = (HINSTANCE)GetModuleHandleW(nullptr);
    static bool registered = false;
    if (!registered) {
        WNDCLASSW wc{};
        wc.lpfnWndProc = LibraryDropWndProc;
        wc.hInstance = hinst;
        wc.lpszClassName = L"LinyuKouziLibraryDrop";
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
        RegisterClassW(&wc);
        registered = true;
    }

    RECT pr{};
    GetWindowRect(parent, &pr);
    int w = 470, h = 340;
    int x = pr.left + ((pr.right - pr.left) - w) / 2;
    int y = pr.top + ((pr.bottom - pr.top) - h) / 2;
    LibraryDropState state;
    EnableWindow(parent, FALSE);
    HWND dlg = CreateWindowExW(WS_EX_DLGMODALFRAME, L"LinyuKouziLibraryDrop", L"添加词库",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, x, y, w, h, parent, nullptr, hinst, &state);
    ShowWindow(dlg, SW_SHOW);
    UpdateWindow(dlg);
    MSG msg{};
    while (!state.done && GetMessageW(&msg, nullptr, 0, 0) > 0) {
        if (!IsDialogMessageW(dlg, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    EnableWindow(parent, TRUE);
    SetForegroundWindow(parent);
    if (state.ok && !state.file.empty()) {
        file = state.file;
        name = state.name;
        return true;
    }
    return false;
}

static void AddTextLibraryFlow() {
    std::wstring file;
    std::wstring name;
    if (ShowLibraryDropDialog(g_app.hwnd, file, name)) AddTextLibraryFromFile(file, name);
}

static void RemoveCurrentLibrary() {
    if (g_app.librarySel < 0 || g_app.librarySel >= static_cast<int>(g_textLibraries.size())) {
        MessageBoxW(g_app.hwnd, L"当前没有选中的词库。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
        return;
    }
    std::wstring name = g_textLibraries[g_app.librarySel].name;
    if (MessageBoxW(g_app.hwnd, (L"删除词库“" + name + L"”？不会影响原来的 txt 文件。").c_str(),
        APP_TITLE, MB_OKCANCEL | MB_ICONQUESTION) != IDOK) {
        return;
    }
    g_textLibraries.erase(g_textLibraries.begin() + g_app.librarySel);
    if (g_textLibraries.empty()) {
        g_app.librarySel = -1;
        SetWindowTextW(g_app.pathEdit, L"");
    } else {
        g_app.librarySel = std::min(g_app.librarySel, static_cast<int>(g_textLibraries.size()) - 1);
        SetWindowTextW(g_app.pathEdit, g_textLibraries[g_app.librarySel].path.c_str());
    }
    SaveTextLibraries();
    UpdateLibraryButtonText();
    SaveConfig();
    SetWindowTextW(g_app.status, L"词库已删除。");
}

static void ShowTextLibraryMenu() {
    HMENU menu = CreatePopupMenu();
    if (g_textLibraries.empty()) {
        AppendMenuW(menu, MF_STRING | MF_GRAYED, 900, L"暂无词库");
    } else {
        for (int i = 0; i < static_cast<int>(g_textLibraries.size()); ++i) {
            AppendMenuW(menu, MF_STRING | (i == g_app.librarySel ? MF_CHECKED : 0),
                1000 + i, g_textLibraries[i].name.c_str());
        }
    }
    RECT rc{};
    GetWindowRect(g_app.librarySelect, &rc);
    int cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN, rc.left, rc.bottom + 4, 0, g_app.hwnd, nullptr);
    DestroyMenu(menu);
    if (cmd >= 1000 && cmd < 1000 + static_cast<int>(g_textLibraries.size())) {
        SelectTextLibrary(cmd - 1000);
    }
}

static int ShowPopupChoice(HWND owner, HWND anchor, const std::vector<const wchar_t*>& items, int current) {
    HMENU menu = CreatePopupMenu();
    for (int i = 0; i < static_cast<int>(items.size()); ++i) {
        AppendMenuW(menu, MF_STRING | (i == current ? MF_CHECKED : 0), 1000 + i, items[i]);
    }
    RECT rc{};
    GetWindowRect(anchor, &rc);
    int cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_TOPALIGN, rc.left, rc.bottom + 4, 0, owner, nullptr);
    DestroyMenu(menu);
    if (cmd >= 1000 && cmd < 1000 + static_cast<int>(items.size())) return cmd - 1000;
    return current;
}

static void UpdatePopupTexts() {
    static const wchar_t* inputText[] = { L"微软候选  ▾", L"拼音输入法  ▾", L"精确逐字  ▾" };
    static const wchar_t* chunkText[] = { L"随机分词  ▾", L"整句上屏  ▾", L"逐字上屏  ▾" };
    static const wchar_t* enterText[] = { L"enter  ▾", L"ctrl+enter  ▾", L"不自动回车  ▾" };
    static const wchar_t* mentionText[] = { L"不@  ▾", L"每句@  ▾", L"随机@  ▾", L"隔句@  ▾", L"直接@  ▾" };
    if (g_app.inputMode) SetWindowTextW(g_app.inputMode, inputText[g_app.inputModeSel]);
    if (g_app.inputLayout) {
        std::wstring layout = L"当前输入法";
        if (g_app.inputLayoutSel >= 0 && g_app.inputLayoutSel < static_cast<int>(g_inputLayouts.size())) {
            layout = g_inputLayouts[g_app.inputLayoutSel].name;
        }
        layout = ShortText(layout, 16) + L"  ▾";
        SetWindowTextW(g_app.inputLayout, layout.c_str());
        InvalidateRect(g_app.inputLayout, nullptr, TRUE);
    }
    if (g_app.chunkMode) SetWindowTextW(g_app.chunkMode, chunkText[g_app.chunkModeSel]);
    if (g_app.enterMode) SetWindowTextW(g_app.enterMode, enterText[g_app.enterModeSel]);
    if (g_app.mentionMode) SetWindowTextW(g_app.mentionMode, mentionText[g_app.mentionModeSel]);
    UpdateLibraryButtonText();
    if (g_app.inputMode) InvalidateRect(g_app.inputMode, nullptr, TRUE);
    if (g_app.chunkMode) InvalidateRect(g_app.chunkMode, nullptr, TRUE);
    if (g_app.enterMode) InvalidateRect(g_app.enterMode, nullptr, TRUE);
    if (g_app.mentionMode) InvalidateRect(g_app.mentionMode, nullptr, TRUE);
}

struct AvatarResult {
    UINT serial = 0;
    std::wstring qq;
    std::vector<BYTE> bytes;
    bool ok = false;
};

static void InvalidateMentionAvatar() {
    if (g_app.mentionAvatar && IsWindow(g_app.mentionAvatar)) {
        InvalidateRect(g_app.mentionAvatar, nullptr, TRUE);
    }
}

static void RequestQqAvatarPreview(const std::wstring& rawQq) {
    std::wstring qq = ExtractQqNumber(rawQq);
    UINT serial = ++g_avatarRequestSerial;
    g_app.mentionAvatarSerial = serial;
    g_app.mentionAvatarQq = qq;
    g_app.mentionAvatarBytes.clear();
    g_app.mentionAvatarFailed = false;
    g_app.mentionAvatarLoading = qq.size() >= 5;
    InvalidateMentionAvatar();

    if (!g_app.mentionAvatarLoading) return;
    HWND target = g_app.hwnd;
    std::thread([target, serial, qq]() {
        auto* result = new AvatarResult;
        result->serial = serial;
        result->qq = qq;
        result->ok = FetchQqAvatarBytes(qq, result->bytes);
        if (!target || !PostMessageW(target, WM_QQ_AVATAR_DONE, 0, reinterpret_cast<LPARAM>(result))) {
            delete result;
        }
    }).detach();
}

static void RefreshQqAvatarPreviewFromEdit() {
    if (!g_app.mentionQqEdit) return;
    RequestQqAvatarPreview(GetWindowTextString(g_app.mentionQqEdit));
}

static void OnMentionQqChanged() {
    if (!g_app.mentionQqEdit || g_mentionQqInternalChange) return;
    std::wstring raw = GetWindowTextString(g_app.mentionQqEdit);
    std::wstring qq = ExtractQqNumber(raw);
    if (raw != qq) {
        g_mentionQqInternalChange = true;
        SetWindowTextW(g_app.mentionQqEdit, qq.c_str());
        SendMessageW(g_app.mentionQqEdit, EM_SETSEL, qq.size(), qq.size());
        g_mentionQqInternalChange = false;
    }
    if (qq != g_app.mentionAvatarQq) {
        RequestQqAvatarPreview(qq);
    }
}
