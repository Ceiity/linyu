// 字体应用、开关/按钮绘制、主窗口消息处理
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static void SetFontRecursive(HWND parent) {
    HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    EnumChildWindows(parent, [](HWND child, LPARAM lParam) -> BOOL {
        SendMessageW(child, WM_SETFONT, (WPARAM)lParam, TRUE);
        return TRUE;
    }, (LPARAM)font);
}

static bool IsCheckControl(UINT id) {
    return id == ID_HUMANIZE
        || id == ID_PREVIEW_BEFORE
        || id == ID_SOUND
        || id == ID_CORRECTION_EFFECT
        || id == ID_CHECK_FOREGROUND
        || id == ID_NAPCAT_USE_CONTEXT
        || id == ID_NAPCAT_ONLY_AT;
}

static void DrawOwnerSwitch(const DRAWITEMSTRUCT* item) {
    bool checked = GetSwitchState(item->CtlID);
    RECT rc = item->rcItem;
    FillRect(item->hDC, &rc, g_cardBrush);

    int switchW = 42;
    int switchH = 24;
    int top = rc.top + (rc.bottom - rc.top - switchH) / 2;
    RECT sw{ rc.left, top, rc.left + switchW, top + switchH };

    DrawRoundPanel(item->hDC, sw, checked ? C_ACCENT : RGB(218, 218, 224), checked ? C_ACCENT : RGB(218, 218, 224), switchH);

    int knob = 20;
    int knobLeft = checked ? sw.right - knob - 2 : sw.left + 2;
    RECT kb{ knobLeft, sw.top + 2, knobLeft + knob, sw.top + 2 + knob };
    HBRUSH knobBrush = CreateSolidBrush(RGB(255, 255, 255));
    HPEN knobPen = CreatePen(PS_SOLID, 1, RGB(210, 210, 216));
    HGDIOBJ oldBrush = SelectObject(item->hDC, knobBrush);
    HGDIOBJ oldPen = SelectObject(item->hDC, knobPen);
    Ellipse(item->hDC, kb.left, kb.top, kb.right, kb.bottom);
    SelectObject(item->hDC, oldPen);
    SelectObject(item->hDC, oldBrush);
    DeleteObject(knobPen);
    DeleteObject(knobBrush);

    wchar_t textBuf[160]{};
    GetWindowTextW(item->hwndItem, textBuf, 160);
    RECT textRc{ rc.left + switchW + 10, rc.top, rc.right, rc.bottom };
    SetBkMode(item->hDC, TRANSPARENT);
    SetTextColor(item->hDC, C_TEXT);
    HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HGDIOBJ oldFont = SelectObject(item->hDC, font);
    DrawTextW(item->hDC, textBuf, -1, &textRc, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    SelectObject(item->hDC, oldFont);
}

static void DrawOwnerButton(const DRAWITEMSTRUCT* item) {
    if (IsCheckControl(item->CtlID)) {
        DrawOwnerSwitch(item);
        return;
    }

    bool pressed = (item->itemState & ODS_SELECTED) != 0;
    bool disabled = (item->itemState & ODS_DISABLED) != 0;
    COLORREF fill = C_CONTROL;
    COLORREF border = C_BORDER;
    COLORREF text = C_TEXT;

    if (item->CtlID == ID_START || item->CtlID == ID_AI_START || item->CtlID == IDOK) {
        fill = pressed ? C_ACCENT_DARK : C_ACCENT;
        border = C_ACCENT;
        text = RGB(255, 255, 255);
    } else if ((item->CtlID == ID_PAGE_SEND && g_app.activePage == 0)
        || (item->CtlID == ID_PAGE_AI && g_app.activePage == 1)
        || (item->CtlID == ID_PAGE_NAPCAT && g_app.activePage == 2)) {
        fill = pressed ? C_ACCENT_DARK : C_ACCENT;
        border = C_ACCENT;
        text = RGB(255, 255, 255);
    } else if (item->CtlID == ID_STOP) {
        fill = pressed ? RGB(210, 45, 40) : C_DANGER;
        border = C_DANGER;
        text = RGB(255, 255, 255);
    } else if (item->CtlID == ID_CONTINUE_SEND) {
        fill = pressed ? C_WARNING_DARK : C_WARNING;
        border = C_WARNING;
        text = RGB(45, 32, 0);
    } else if (item->CtlID == ID_INPUT_MODE || item->CtlID == ID_INPUT_LAYOUT || item->CtlID == ID_CHUNK_MODE
        || item->CtlID == ID_ENTER_MODE || item->CtlID == ID_LIBRARY_SELECT || item->CtlID == ID_MENTION_MODE) {
        fill = pressed ? RGB(229, 229, 234) : C_CONTROL;
        border = RGB(210, 210, 216);
    } else if (pressed) {
        fill = RGB(229, 229, 234);
    }
    if (disabled) {
        fill = RGB(229, 229, 234);
        text = RGB(142, 142, 147);
    }

    RECT rc = item->rcItem;
    DrawRoundPanel(item->hDC, rc, fill, border, 14);

    wchar_t textBuf[128]{};
    GetWindowTextW(item->hwndItem, textBuf, 128);
    SetBkMode(item->hDC, TRANSPARENT);
    SetTextColor(item->hDC, text);
    HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HGDIOBJ oldFont = SelectObject(item->hDC, font);
    DrawTextW(item->hDC, textBuf, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    SelectObject(item->hDC, oldFont);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_CREATE: {
        g_app.hwnd = hwnd;
        BOOL dark = FALSE;
        DwmSetWindowAttribute(hwnd, 20, &dark, sizeof(dark));
        DwmSetWindowAttribute(hwnd, 19, &dark, sizeof(dark));
        g_bgBrush = CreateSolidBrush(C_BG);
        g_cardBrush = CreateSolidBrush(C_CARD);
        g_controlBrush = CreateSolidBrush(C_CONTROL);
        DragAcceptFiles(hwnd, TRUE);
        LoadInputLayouts();
        g_app.uiFont = CreateFontW(-15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Microsoft YaHei UI");
        g_app.titleFont = CreateFontW(-26, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Microsoft YaHei UI");

        g_app.titleLabel = MakeLabel(hwnd, APP_TITLE, 32, 20, 240, 34);
        g_app.subtitleLabel = MakeLabel(hwnd, L"纯发送词库版。点击开始，然后点一下聊天框。", 34, 56, 620, 24);
        g_mouseHook = SetWindowsHookExW(WH_MOUSE, MainMouseHookProc, nullptr, GetCurrentThreadId());
        TrackPage(MakeGroup(hwnd, L"词库", 24, 88, 700, 190), 0);
        TrackPage(MakeLabel(hwnd, L"常用文本", 48, 126, 90, 22), 0);
        g_app.librarySelect = TrackPage(MakePopupButton(hwnd, ID_LIBRARY_SELECT, L"选择词库  ▾", 48, 154, 280), 0);
        TrackPage(MakeButton(hwnd, ID_LIBRARY_ADD, L"添加词库", 340, 152, 112, 36), 0);
        TrackPage(MakeButton(hwnd, ID_LIBRARY_REMOVE, L"删除", 464, 152, 112, 36), 0);
        TrackPage(MakeButton(hwnd, ID_BROWSE, L"选择txt", 588, 152, 112, 36), 0);
        TrackPage(MakeLabel(hwnd, L"当前文本", 48, 200, 90, 22), 0);
        g_app.pathEdit = TrackPage(MakeEdit(hwnd, ID_PATH, L"", 48, 228, 652, 32), 0);

        TrackPage(MakeGroup(hwnd, L"群聊 @", 24, 296, 700, 120), 0);
        g_app.mentionAvatar = TrackPage(MakeAvatar(hwnd, ID_MENTION_AVATAR, 48, 342, 54), 0);
        g_app.mentionQqEdit = TrackPage(MakeEdit(hwnd, ID_MENTION_QQ, L"", 118, 352, 164, 32), 0);
        g_app.mentionMode = TrackPage(MakePopupButton(hwnd, ID_MENTION_MODE, L"不@  ▾", 306, 352, 132), 0);
        TrackPage(MakeLabel(hwnd, L"直接@：只选人并发送。", 462, 355, 240, 24), 0);

        TrackPage(MakeGroup(hwnd, L"输入", 24, 434, 700, 122), 0);
        TrackPage(MakeLabel(hwnd, L"输入方式", 48, 464, 120, 22), 0);
        g_app.inputMode = TrackPage(MakePopupButton(hwnd, ID_INPUT_MODE, L"微软候选  ▾", 48, 488, 132), 0);
        TrackPage(MakeLabel(hwnd, L"输入法", 198, 464, 120, 22), 0);
        g_app.inputLayout = TrackPage(MakePopupButton(hwnd, ID_INPUT_LAYOUT, L"当前输入法  ▾", 198, 488, 246), 0);
        TrackPage(MakeLabel(hwnd, L"分词", 462, 464, 92, 22), 0);
        g_app.chunkMode = TrackPage(MakePopupButton(hwnd, ID_CHUNK_MODE, L"整句上屏  ▾", 462, 488, 108), 0);
        TrackPage(MakeLabel(hwnd, L"发送键", 588, 464, 92, 22), 0);
        g_app.enterMode = TrackPage(MakePopupButton(hwnd, ID_ENTER_MODE, L"enter  ▾", 588, 488, 112), 0);
        g_app.previewBefore = TrackPage(MakeCheck(hwnd, ID_PREVIEW_BEFORE, L"发送前预览", 48, 522, 132, 28, false), 0);
        g_app.sound = TrackPage(MakeCheck(hwnd, ID_SOUND, L"机械键盘音", 204, 522, 132, 28, false), 0);
        g_app.humanize = TrackPage(MakeCheck(hwnd, ID_HUMANIZE, L"随机真人节奏", 360, 522, 152, 28, true), 0);
        g_app.correctionEffect = TrackPage(MakeCheck(hwnd, ID_CORRECTION_EFFECT, L"稳字纠错", 538, 522, 132, 28, true), 0);

        TrackPage(MakeGroup(hwnd, L"节奏", 24, 574, 700, 112), 0);
        TrackPage(MakeLabel(hwnd, L"按键", 48, 608, 92, 22), 0);
        g_app.keyDelayEdit = TrackPage(MakeEdit(hwnd, ID_KEY_DELAY, L"0.012", 48, 636, 92, 32), 0);
        TrackPage(MakeLabel(hwnd, L"候选停留", 158, 608, 92, 22), 0);
        g_app.commitDelayEdit = TrackPage(MakeEdit(hwnd, ID_COMMIT_DELAY, L"0.07", 158, 636, 92, 32), 0);
        TrackPage(MakeLabel(hwnd, L"行间隔", 268, 608, 92, 22), 0);
        g_app.lineDelayEdit = TrackPage(MakeEdit(hwnd, ID_LINE_DELAY, L"0.08", 268, 636, 92, 32), 0);
        TrackPage(MakeLabel(hwnd, L"停顿%", 378, 608, 92, 22), 0);
        g_app.pauseChanceEdit = TrackPage(MakeEdit(hwnd, ID_PAUSE_CHANCE, L"0", 378, 636, 92, 32), 0);
        TrackPage(MakeLabel(hwnd, L"停顿最短", 488, 608, 92, 22), 0);
        g_app.pauseMinEdit = TrackPage(MakeEdit(hwnd, ID_PAUSE_MIN, L"0.05", 488, 636, 92, 32), 0);
        TrackPage(MakeLabel(hwnd, L"停顿最长", 598, 608, 92, 22), 0);
        g_app.pauseMaxEdit = TrackPage(MakeEdit(hwnd, ID_PAUSE_MAX, L"0.12", 598, 636, 92, 32), 0);

        TrackPage(MakeGroup(hwnd, L"安全", 24, 704, 700, 90), 0);
        g_app.checkForeground = TrackPage(MakeCheck(hwnd, ID_CHECK_FOREGROUND, L"点中 QQ/微信才开始；发送中点击鼠标自动停止", 48, 746, 430, 28, true), 0);
        TrackPage(MakeLabel(hwnd, L"取消后会在下一次鼠标点击时直接开打。", 466, 749, 250, 24), 0);

        TrackPage(MakeGroup(hwnd, L"AI 对话", 24, 88, 700, 598), 1);
        TrackPage(MakeLabel(hwnd, L"DeepSeek API Key", 48, 124, 150, 22), 1);
        g_app.aiApiKeyEdit = TrackPage(MakePasswordEdit(hwnd, ID_AI_API_KEY, L"", 48, 150, 300, 32), 1);
        TrackPage(MakeLabel(hwnd, L"连续句数", 374, 124, 92, 22), 1);
        g_app.aiCountEdit = TrackPage(MakeEdit(hwnd, ID_AI_COUNT, L"10", 374, 150, 96, 32), 1);
        TrackPage(MakeButton(hwnd, ID_AI_GENERATE, L"AI生成", 494, 148, 96, 36), 1);
        TrackPage(MakeButton(hwnd, ID_AI_START, L"AI开始发送", 604, 148, 96, 36), 1);

        TrackPage(MakeLabel(hwnd, L"NapCat WS", 48, 196, 120, 22), 1);
        g_app.napcatUrlEdit = TrackPage(MakeEdit(hwnd, ID_NAPCAT_URL, L"ws://127.0.0.1:3001", 48, 222, 302, 32), 1);
        TrackPage(MakeLabel(hwnd, L"Token", 374, 196, 92, 22), 1);
        g_app.napcatTokenEdit = TrackPage(MakePasswordEdit(hwnd, ID_NAPCAT_TOKEN, L"", 374, 222, 186, 32), 1);
        g_app.napcatToggleButton = TrackPage(MakeButton(hwnd, ID_NAPCAT_TOGGLE, L"连接监听", 580, 220, 120, 36), 1);
        g_app.napcatUseContext = TrackPage(MakeCheck(hwnd, ID_NAPCAT_USE_CONTEXT, L"用最新消息", 48, 266, 150, 28, true), 1);
        g_app.napcatOnlyAt = TrackPage(MakeCheck(hwnd, ID_NAPCAT_ONLY_AT, L"仅@我触发", 220, 266, 150, 28, false), 1);
        g_app.napcatStatus = TrackPage(MakeLabel(hwnd, L"NapCat 未监听。", 396, 270, 304, 22), 1);

        TrackPage(MakeLabel(hwnd, L"人设", 48, 306, 92, 22), 1);
        g_app.aiPersonaEdit = TrackPage(MakeEdit(hwnd, ID_AI_PERSONA, L"", 48, 336, 652, 32), 1);
        TrackPage(MakeLabel(hwnd, L"要求/主题/对方原话", 48, 390, 180, 22), 1);
        g_app.aiPromptEdit = TrackPage(MakeMultiEdit(hwnd, ID_AI_PROMPT, L"", 48, 418, 652, 232), 1);

        TrackPage(MakeGroup(hwnd, L"NapCat 管理", 24, 88, 700, 598), 2);
        TrackPage(MakeLabel(hwnd, L"QQ.exe 路径", 48, 124, 140, 22), 2);
        g_app.napcatQqPathEdit = TrackPage(MakeEdit(hwnd, ID_NAPCAT_QQ_PATH, L"D:\\qq\\QQ.exe", 48, 152, 652, 32), 2);
        HWND napInstall = TrackPage(MakeButton(hwnd, ID_NAPCAT_INSTALL, L"安装/修复 NapCat", 48, 214, 150, 38), 2);
        HWND napStart = TrackPage(MakeButton(hwnd, ID_NAPCAT_START, L"启动 NapCat", 218, 214, 130, 38), 2);
        HWND napWeb = TrackPage(MakeButton(hwnd, ID_NAPCAT_WEBUI, L"WebUI地址", 368, 214, 130, 38), 2);
        HWND napCheck = TrackPage(MakeButton(hwnd, ID_NAPCAT_CHECK, L"检测端口", 518, 214, 130, 38), 2);
        HWND napQr = TrackPage(MakeButton(hwnd, ID_NAPCAT_QR, L"扫码窗口", 48, 270, 130, 36), 2);
        SetWindowSubclass(napInstall, NapcatButtonSubclassProc, ID_NAPCAT_INSTALL, 0);
        SetWindowSubclass(napStart, NapcatButtonSubclassProc, ID_NAPCAT_START, 0);
        SetWindowSubclass(napWeb, NapcatButtonSubclassProc, ID_NAPCAT_WEBUI, 0);
        SetWindowSubclass(napCheck, NapcatButtonSubclassProc, ID_NAPCAT_CHECK, 0);
        SetWindowSubclass(napQr, NapcatButtonSubclassProc, ID_NAPCAT_QR, 0);
        TrackPage(MakeLabel(hwnd, L"二维码只在独立扫码窗口里显示；扫码登录后会自动收起。", 48, 322, 652, 24), 2);
        TrackPage(MakeLabel(hwnd, L"配置步骤：1 安装/修复  2 启动并扫码  3 到 AI 页点连接监听", 48, 358, 430, 24), 2);
        g_app.napcatManagerStatus = TrackPage(MakeLabel(hwnd, L"未启动。先点安装/修复 NapCat，再点启动 NapCat。", 198, 276, 302, 44), 2);
        TrackPage(MakeLabel(hwnd, L"NapCat 日志", 48, 390, 120, 22), 2);
        g_app.napcatLogEdit = TrackPage(MakeLogEdit(hwnd, ID_NAPCAT_LOG, 48, 418, 652, 232), 2);

        MakeButton(hwnd, ID_RESET_CONFIG, L"重置配置", 112, 900, 112, 36);
        MakeButton(hwnd, ID_PREVIEW, L"预览", 238, 900, 96, 36);
        MakeButton(hwnd, ID_STOP, L"重置进度", 348, 900, 112, 36);
        MakeButton(hwnd, ID_CONTINUE_SEND, L"继续发送", 474, 900, 112, 36);
        MakeButton(hwnd, ID_START, L"开始发送", 600, 900, 124, 36);
        g_app.status = CreateWindowExW(0, L"STATIC", L"准备就绪。拖入文本后点击开始发送。",
            WS_CHILD | WS_VISIBLE | SS_LEFT, 48, 836, 650, 24, hwnd, nullptr, nullptr, nullptr);
        LoadTextLibraries();
        LoadSavedConfig();
        SetActivePage(g_app.activePage);
        SetFontRecursive(hwnd);
        SendMessageW(g_app.titleLabel, WM_SETFONT, (WPARAM)g_app.titleFont, TRUE);
        CaptureBaseLayout(hwnd);
        LayoutMainWindow(hwnd);
        SetTimer(hwnd, 1, 1000, nullptr);
        RefreshNapcatLog();
        SetActivePage(g_app.activePage);
        RefreshNapcatPortState();
        RegisterStealthHotkeys(hwnd);
        return 0;
    }
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(hwnd, &ps);
        DrawUiBackground(hwnd, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_GETMINMAXINFO: {
        auto* info = reinterpret_cast<MINMAXINFO*>(lParam);
        info->ptMinTrackSize.x = MIN_WINDOW_W;
        info->ptMinTrackSize.y = MIN_WINDOW_H;
        return 0;
    }
    case WM_SIZE:
        LayoutMainWindow(hwnd);
        return 0;
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)wParam;
        HWND child = (HWND)lParam;
        SetBkMode(dc, TRANSPARENT);
        if (child == g_app.titleLabel || child == g_app.subtitleLabel) {
            SetTextColor(dc, child == g_app.titleLabel ? C_TEXT : C_MUTED);
            return (LRESULT)g_bgBrush;
        }
        if (child == g_app.status) {
            SetTextColor(dc, C_MUTED);
            return (LRESULT)g_cardBrush;
        }
        if (child == g_app.napcatLogEdit) {
            SetTextColor(dc, C_TEXT);
            SetBkMode(dc, OPAQUE);
            SetBkColor(dc, C_CONTROL);
            return (LRESULT)g_controlBrush;
        }
        SetTextColor(dc, C_TEXT);
        return (LRESULT)g_cardBrush;
    }
    case WM_CTLCOLOREDIT: {
        HDC dc = (HDC)wParam;
        HWND child = (HWND)lParam;
        SetTextColor(dc, C_TEXT);
        SetBkColor(dc, C_CONTROL);
        if (child == g_app.napcatLogEdit) SetBkMode(dc, OPAQUE);
        return (LRESULT)g_controlBrush;
    }
    case WM_CTLCOLORLISTBOX: {
        HDC dc = (HDC)wParam;
        SetTextColor(dc, C_TEXT);
        SetBkColor(dc, C_CONTROL);
        return (LRESULT)g_controlBrush;
    }
    case WM_CTLCOLORBTN: {
        HDC dc = (HDC)wParam;
        SetTextColor(dc, C_TEXT);
        SetBkMode(dc, TRANSPARENT);
        return (LRESULT)g_cardBrush;
    }
    case WM_DRAWITEM:
        DrawOwnerButton(reinterpret_cast<DRAWITEMSTRUCT*>(lParam));
        return TRUE;
    case WM_TIMER: {
        if (wParam == 1) {
            WIN32_FILE_ATTRIBUTE_DATA data{};
            if (g_app.activePage == 2) {
                if (GetFileAttributesExW(NapcatLogPath().c_str(), GetFileExInfoStandard, &data)) {
                    DWORD tick = data.ftLastWriteTime.dwLowDateTime ^ data.ftLastWriteTime.dwHighDateTime;
                    if (tick != g_app.lastNapcatLogTick) {
                        g_app.lastNapcatLogTick = tick;
                        RefreshNapcatLog();
                    }
                }
            }
            if (GetFileAttributesExW(NapcatQrPath().c_str(), GetFileExInfoStandard, &data)) {
                DWORD tick = data.ftLastWriteTime.dwLowDateTime ^ data.ftLastWriteTime.dwHighDateTime;
                if (tick != g_app.lastNapcatQrTick) {
                    g_app.lastNapcatQrTick = tick;
                    if (g_app.napcatQrWindow && IsWindow(g_app.napcatQrWindow)) {
                        InvalidateRect(g_app.napcatQrWindow, nullptr, TRUE);
                    }
                    InvalidateNapcatQrCard();
                }
            }
            RefreshNapcatPortState();
        }
        return 0;
    }
    case WM_HOTKEY: {
        HandleStealthHotkey(hwnd, wParam);
        return 0;
    }
    case WM_DROPFILES: {
        HDROP drop = (HDROP)wParam;
        wchar_t file[MAX_PATH]{};
        if (DragQueryFileW(drop, 0, file, MAX_PATH)) {
            g_app.librarySel = -1;
            SetWindowTextW(g_app.pathEdit, file);
            UpdateLibraryButtonText();
            SetWindowTextW(g_app.status, L"已载入文件。需要常用的话可以点“添加词库”。");
            SaveConfig();
        }
        DragFinish(drop);
        return 0;
    }
    case WM_COMMAND: {
        switch (LOWORD(wParam)) {
        case ID_PAGE_SEND:
            SetActivePage(0);
            SaveConfig();
            return 0;
        case ID_PAGE_AI:
            SetActivePage(1);
            SaveConfig();
            return 0;
        case ID_PAGE_NAPCAT:
            SetActivePage(2);
            SaveConfig();
            return 0;
        case ID_NAPCAT_INSTALL:
            RunNapcatManager(L"install");
            SaveConfig();
            return 0;
        case ID_NAPCAT_START:
            RunNapcatManager(L"start");
            SaveConfig();
            return 0;
        case ID_NAPCAT_WEBUI:
            OpenNapcatWebUi();
            return 0;
        case ID_NAPCAT_CHECK:
            ShowNapcatCheckCommand();
            return 0;
        case ID_NAPCAT_QR:
            OpenNapcatQr();
            return 0;
        case ID_BROWSE: BrowseFile(); return 0;
        case ID_LIBRARY_SELECT:
            ShowTextLibraryMenu();
            return 0;
        case ID_LIBRARY_ADD:
            AddTextLibraryFlow();
            return 0;
        case ID_LIBRARY_REMOVE:
            RemoveCurrentLibrary();
            return 0;
        case ID_MENTION_QQ:
            if (HIWORD(wParam) == EN_CHANGE) {
                if (!g_applyingConfig) {
                    OnMentionQqChanged();
                    SaveConfig();
                }
            }
            return 0;
        case ID_RESET_CONFIG:
            ResetConfig();
            return 0;
        case ID_AI_GENERATE:
            GenerateAiText();
            return 0;
        case ID_AI_START:
            StartAiOrPreset();
            return 0;
        case ID_NAPCAT_TOGGLE:
            ToggleNapcatListening();
            return 0;
        case ID_HUMANIZE:
        case ID_PREVIEW_BEFORE:
        case ID_SOUND:
        case ID_CORRECTION_EFFECT:
        case ID_CHECK_FOREGROUND:
        case ID_NAPCAT_USE_CONTEXT:
        case ID_NAPCAT_ONLY_AT: {
            UINT id = LOWORD(wParam);
            DWORD now = GetTickCount();
            if (HIWORD(wParam) == BN_CLICKED && !(g_app.lastSwitchId == id && now - g_app.lastSwitchTick < 180)) {
                HWND ctl = reinterpret_cast<HWND>(lParam);
                if (!ctl) ctl = GetDlgItem(hwnd, id);
                if (ctl) ToggleSwitch(ctl);
            }
            SaveConfig();
            return 0;
        }
        case ID_INPUT_MODE:
            g_app.inputModeSel = ShowPopupChoice(hwnd, g_app.inputMode, { L"微软候选", L"拼音输入法", L"精确逐字" }, g_app.inputModeSel);
            UpdatePopupTexts();
            SaveConfig();
            return 0;
        case ID_INPUT_LAYOUT: {
            std::vector<const wchar_t*> items;
            for (const auto& layout : g_inputLayouts) items.push_back(layout.name.c_str());
            if (!items.empty()) {
                g_app.inputLayoutSel = ShowPopupChoice(hwnd, g_app.inputLayout, items, g_app.inputLayoutSel);
                UpdatePopupTexts();
                SaveConfig();
            }
            return 0;
        }
        case ID_CHUNK_MODE:
            g_app.chunkModeSel = ShowPopupChoice(hwnd, g_app.chunkMode, { L"随机分词", L"整句上屏", L"逐字上屏" }, g_app.chunkModeSel);
            UpdatePopupTexts();
            SaveConfig();
            return 0;
        case ID_ENTER_MODE:
            g_app.enterModeSel = ShowPopupChoice(hwnd, g_app.enterMode, { L"enter", L"ctrl+enter", L"不自动回车" }, g_app.enterModeSel);
            UpdatePopupTexts();
            SaveConfig();
            return 0;
        case ID_MENTION_MODE:
            g_app.mentionModeSel = ShowPopupChoice(hwnd, g_app.mentionMode, { L"不@", L"每句@", L"随机@", L"隔几句随机@", L"直接@" }, g_app.mentionModeSel);
            if (g_app.mentionModeSel == 0 && g_app.mentionQqEdit) SetWindowTextW(g_app.mentionQqEdit, L"");
            UpdatePopupTexts();
            SaveConfig();
            return 0;
        case ID_PREVIEW: {
            auto path = GetWindowTextString(g_app.pathEdit);
            if (path.empty()) {
                MessageBoxW(hwnd, L"请先选择 txt 文件。", APP_TITLE, MB_OK | MB_ICONINFORMATION);
                return 0;
            }
            MessageBoxW(hwnd, BuildPreview(ReadTextFile(path), ReadSettings()).c_str(), L"发送前预览", MB_OK | MB_ICONINFORMATION);
            return 0;
        }
        case ID_STOP:
            if (g_app.running.load()) {
                g_app.stop = true;
                ResetSendProgressForPath(GetWindowTextString(g_app.pathEdit));
                SetWindowTextW(g_app.status, L"已停止，并已重置进度。下次开始会从第一行发送。");
            } else {
                ResetSendProgressForPath(GetWindowTextString(g_app.pathEdit));
                SetWindowTextW(g_app.status, L"发送进度已重置。点击开始发送会从第一行开始。");
            }
            return 0;
        case ID_CONTINUE_SEND:
            StartSending(true);
            return 0;
        case ID_START:
            StartSending(false);
            return 0;
        case IDOK:
            DestroyWindow(GetParent((HWND)lParam));
            return 0;
        }
        break;
    }
    case WM_STATUS: {
        std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lParam));
        SetWindowTextW(g_app.status, text->c_str());
        return 0;
    }
    case WM_AI_DONE: {
        std::unique_ptr<std::wstring> path(reinterpret_cast<std::wstring*>(lParam));
        bool startAfterDone = g_app.aiStartAfterDone;
        g_app.aiStartAfterDone = false;
        g_app.aiGenerating = false;
        SetWindowTextW(g_app.pathEdit, path->c_str());
        SetWindowTextW(g_app.status, startAfterDone ? L"AI 已生成，准备发送。请点一下聊天框。" : L"AI 已生成文本，并已载入文本文件。");
        SaveConfig();
        if (startAfterDone) StartSending();
        return 0;
    }
    case WM_AI_FAILED: {
        std::unique_ptr<std::wstring> error(reinterpret_cast<std::wstring*>(lParam));
        g_app.aiStartAfterDone = false;
        g_app.aiGenerating = false;
        std::wstring msg = L"AI 生成失败：" + *error;
        SetWindowTextW(g_app.status, msg.c_str());
        MessageBoxW(hwnd, msg.c_str(), APP_TITLE, MB_OK | MB_ICONERROR);
        return 0;
    }
    case WM_NAPCAT_STATUS: {
        std::unique_ptr<std::wstring> text(reinterpret_cast<std::wstring*>(lParam));
        if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, text->c_str());
        if (g_app.napcatToggleButton) SetWindowTextW(g_app.napcatToggleButton, g_app.napcatRunning.load() ? L"停止监听" : L"连接监听");
        return 0;
    }
    case WM_NAPCAT_EVENT: {
        std::unique_ptr<NapcatEvent> event(reinterpret_cast<NapcatEvent*>(lParam));
        g_app.lastNapcatText = event->text;
        g_app.lastNapcatRaw = event->raw;
        g_app.lastNapcatUserId = event->userId;
        g_app.lastNapcatGroupId = event->groupId;
        g_app.lastNapcatName = event->nickname;
        g_app.lastNapcatType = event->messageType;
        g_app.lastNapcatTick = GetTickCount64();
        std::wstring line = L"最新：" + ShortText(event->nickname, 8) + L"：" + ShortText(event->text, 18);
        if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, line.c_str());
        AppendNapcatLogLine(L"[QQ] " + event->nickname + L": " + event->text);
        RefreshNapcatLog();
        SetWindowTextW(g_app.status, L"NapCat 收到新消息，可点 AI开始发送。");
        return 0;
    }
    case WM_QQ_AVATAR_DONE: {
        std::unique_ptr<AvatarResult> result(reinterpret_cast<AvatarResult*>(lParam));
        if (result && result->serial == g_app.mentionAvatarSerial && result->qq == g_app.mentionAvatarQq) {
            g_app.mentionAvatarLoading = false;
            g_app.mentionAvatarFailed = !result->ok;
            g_app.mentionAvatarBytes = result->ok ? std::move(result->bytes) : std::vector<BYTE>{};
            InvalidateMentionAvatar();
        }
        return 0;
    }
    case WM_DESTROY:
        KillTimer(hwnd, 1);
        CloseNapcatQrWindow();
        if (g_mouseHook) {
            UnhookWindowsHookEx(g_mouseHook);
            g_mouseHook = nullptr;
        }
        g_app.stop = true;
        g_app.napcatRunning = false;
        SaveConfig();
        if (g_sound.out) {
            waveOutReset(g_sound.out);
            waveOutClose(g_sound.out);
            g_sound.out = nullptr;
        }
        if (g_bgBrush) DeleteObject(g_bgBrush);
        if (g_cardBrush) DeleteObject(g_cardBrush);
        if (g_controlBrush) DeleteObject(g_controlBrush);
        if (g_app.uiFont) DeleteObject(g_app.uiFont);
        if (g_app.titleFont) DeleteObject(g_app.titleFont);
        if (g_gdiplusToken) {
            Gdiplus::GdiplusShutdown(g_gdiplusToken);
            g_gdiplusToken = 0;
        }
        PostQuitMessage(0);
        UnregisterStealthHotkeys(hwnd);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}
