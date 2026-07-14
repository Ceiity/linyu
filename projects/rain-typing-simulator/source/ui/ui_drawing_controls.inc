// UI 绘制、缩放布局、二维码/头像控件、基础控件创建、页面切换、预览弹窗
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static HWND MakeLabel(HWND parent, const wchar_t* text, int x, int y, int w, int h) {
    return CreateWindowW(L"STATIC", text, WS_CHILD | WS_VISIBLE, x, y, w, h, parent, nullptr, nullptr, nullptr);
}

static std::wstring NapcatQrPath();

static void DrawRoundPanel(HDC dc, RECT rc, COLORREF fill, COLORREF border, int radius = 18) {
    HBRUSH brush = CreateSolidBrush(fill);
    HPEN pen = CreatePen(PS_SOLID, 1, border);
    HGDIOBJ oldBrush = SelectObject(dc, brush);
    HGDIOBJ oldPen = SelectObject(dc, pen);
    RoundRect(dc, rc.left, rc.top, rc.right, rc.bottom, radius, radius);
    SelectObject(dc, oldPen);
    SelectObject(dc, oldBrush);
    DeleteObject(pen);
    DeleteObject(brush);
}

static void DrawCenteredText(HDC dc, RECT rc, const wchar_t* text, COLORREF color) {
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, color);
    HFONT font = g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HGDIOBJ oldFont = SelectObject(dc, font);
    DrawTextW(dc, text, -1, &rc, DT_CENTER | DT_VCENTER | DT_WORDBREAK);
    SelectObject(dc, oldFont);
}

static void InvalidateNapcatQrCard() {
    if (!g_app.hwnd || g_app.activePage != 2) return;
    RECT rc{ 496, 266, 704, 474 };
    InvalidateRect(g_app.hwnd, &rc, TRUE);
}

static RECT ScaleRectForClient(HWND hwnd, RECT rc) {
    RECT client{};
    GetClientRect(hwnd, &client);
    int cw = std::max(1, static_cast<int>(client.right - client.left));
    int ch = std::max(1, static_cast<int>(client.bottom - client.top));
    return RECT{
        MulDiv(rc.left, cw, BASE_CLIENT_W),
        MulDiv(rc.top, ch, BASE_CLIENT_H),
        MulDiv(rc.right, cw, BASE_CLIENT_W),
        MulDiv(rc.bottom, ch, BASE_CLIENT_H)
    };
}

static void MoveScaledWindow(HWND parent, HWND child, RECT baseRect) {
    if (!child || !IsWindow(child)) return;
    RECT rc = ScaleRectForClient(parent, baseRect);
    int w = std::max(1, static_cast<int>(rc.right - rc.left));
    int h = std::max(1, static_cast<int>(rc.bottom - rc.top));
    SetWindowPos(child, nullptr, rc.left, rc.top, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
}

static BOOL CALLBACK CaptureBaseChildProc(HWND child, LPARAM parentParam) {
    HWND parent = reinterpret_cast<HWND>(parentParam);
    if (GetParent(child) != parent) return TRUE;
    RECT rc{};
    GetWindowRect(child, &rc);
    POINT pts[2]{{ rc.left, rc.top }, { rc.right, rc.bottom }};
    MapWindowPoints(nullptr, parent, pts, 2);
    g_childBaseLayouts.push_back({ child, RECT{ pts[0].x, pts[0].y, pts[1].x, pts[1].y } });
    return TRUE;
}

static void CaptureBaseLayout(HWND hwnd) {
    g_childBaseLayouts.clear();
    EnumChildWindows(hwnd, CaptureBaseChildProc, reinterpret_cast<LPARAM>(hwnd));
    g_layoutCaptured = true;
}

static void LayoutMainWindow(HWND hwnd) {
    if (!g_layoutCaptured) return;
    HDWP batch = BeginDeferWindowPos(static_cast<int>(g_childBaseLayouts.size()));
    for (const auto& item : g_childBaseLayouts) {
        if (!item.hwnd || !IsWindow(item.hwnd)) continue;
        RECT rc = ScaleRectForClient(hwnd, item.rect);
        int w = std::max(1, static_cast<int>(rc.right - rc.left));
        int h = std::max(1, static_cast<int>(rc.bottom - rc.top));
        if (batch) {
            HDWP next = DeferWindowPos(batch, item.hwnd, nullptr, rc.left, rc.top, w, h, SWP_NOZORDER | SWP_NOACTIVATE);
            if (next) batch = next;
            else {
                EndDeferWindowPos(batch);
                batch = nullptr;
                MoveScaledWindow(hwnd, item.hwnd, item.rect);
            }
        } else {
            MoveScaledWindow(hwnd, item.hwnd, item.rect);
        }
    }
    if (batch) EndDeferWindowPos(batch);
    InvalidateRect(hwnd, nullptr, TRUE);
}

static void DrawUiBackground(HWND hwnd, HDC dc) {
    RECT client{};
    GetClientRect(hwnd, &client);
    FillRect(dc, &client, g_bgBrush);
    auto SR = [&](RECT rc) { return ScaleRectForClient(hwnd, rc); };

    if (g_app.activePage == 0) {
        DrawRoundPanel(dc, SR(RECT{ 24, 88, 724, 278 }), C_CARD, C_BORDER, 24);
        DrawRoundPanel(dc, SR(RECT{ 24, 296, 724, 416 }), C_CARD, C_BORDER, 24);
        DrawRoundPanel(dc, SR(RECT{ 24, 434, 724, 556 }), C_CARD, C_BORDER, 24);
        DrawRoundPanel(dc, SR(RECT{ 24, 574, 724, 686 }), C_CARD, C_BORDER, 24);
        DrawRoundPanel(dc, SR(RECT{ 24, 704, 724, 794 }), C_CARD, C_BORDER, 24);
    } else if (g_app.activePage == 1) {
        DrawRoundPanel(dc, SR(RECT{ 24, 88, 724, 686 }), C_CARD, C_BORDER, 24);
    } else {
        DrawRoundPanel(dc, SR(RECT{ 24, 88, 724, 686 }), C_CARD, C_BORDER, 24);
    }
    DrawRoundPanel(dc, SR(RECT{ 24, 818, 724, 870 }), C_CARD, C_BORDER, 18);

    if (g_app.activePage == 0) {
        DrawRoundPanel(dc, SR(RECT{ 48, 228, 700, 260 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 118, 352, 282, 384 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 48, 636, 140, 668 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 158, 636, 250, 668 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 268, 636, 360, 668 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 378, 636, 470, 668 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 488, 636, 580, 668 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 598, 636, 690, 668 }), C_CONTROL, C_BORDER, 12);
    } else if (g_app.activePage == 1) {
        DrawRoundPanel(dc, SR(RECT{ 48, 148, 348, 180 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 374, 148, 470, 180 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 48, 220, 350, 252 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 374, 220, 560, 252 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 48, 334, 700, 366 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 48, 418, 700, 650 }), C_CONTROL, C_BORDER, 12);
    } else {
        DrawRoundPanel(dc, SR(RECT{ 48, 150, 700, 182 }), C_CONTROL, C_BORDER, 12);
        DrawRoundPanel(dc, SR(RECT{ 48, 418, 700, 650 }), C_CONTROL, C_BORDER, 16);
    }
}

static void DrawQrWindow(HWND hwnd, HDC dc) {
    RECT client{};
    GetClientRect(hwnd, &client);
    FillRect(dc, &client, g_bgBrush);
    DrawRoundPanel(dc, { 18, 18, client.right - 18, client.bottom - 18 }, C_CARD, C_BORDER, 24);

    RECT title{ 34, 34, client.right - 34, 60 };
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, C_TEXT);
    HFONT oldFont = (HFONT)SelectObject(dc, g_app.uiFont ? g_app.uiFont : (HFONT)GetStockObject(DEFAULT_GUI_FONT));
    DrawTextW(dc, L"NapCat QQ 扫码登录", -1, &title, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    SelectObject(dc, oldFont);

    int qrSize = std::min(static_cast<int>(client.right - 88), 260);
    int qrLeft = (client.right - qrSize) / 2;
    RECT qrPanel{ qrLeft, 78, qrLeft + qrSize, 78 + qrSize };
    DrawRoundPanel(dc, qrPanel, RGB(255, 255, 255), C_BORDER, 18);

    std::wstring path = NapcatQrPath();
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES || !g_gdiplusToken) {
        DrawCenteredText(dc, qrPanel, L"等待二维码生成", C_MUTED);
    } else {
        Gdiplus::Bitmap bitmap(path.c_str());
        if (bitmap.GetLastStatus() == Gdiplus::Ok && bitmap.GetWidth() > 0 && bitmap.GetHeight() > 0) {
            Gdiplus::Graphics graphics(dc);
            graphics.SetInterpolationMode(Gdiplus::InterpolationModeNearestNeighbor);
            graphics.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHalf);
            Gdiplus::Rect dest(qrPanel.left + 14, qrPanel.top + 14, qrPanel.right - qrPanel.left - 28, qrPanel.bottom - qrPanel.top - 28);
            graphics.DrawImage(&bitmap, dest);
        } else {
            DrawCenteredText(dc, qrPanel, L"二维码还没准备好", C_MUTED);
        }
    }

    RECT hint{ 34, qrPanel.bottom + 18, client.right - 34, qrPanel.bottom + 70 };
    DrawCenteredText(dc, hint, L"用手机 QQ 扫码授权。\n上线后这个窗口会自动关闭。", C_MUTED);
}

static LRESULT CALLBACK QrWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(hwnd, &ps);
        DrawQrWindow(hwnd, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return TRUE;
    case WM_CLOSE:
        g_app.napcatQrVisible = false;
        DestroyWindow(hwnd);
        InvalidateNapcatQrCard();
        return 0;
    case WM_DESTROY:
        if (g_app.napcatQrWindow == hwnd) g_app.napcatQrWindow = nullptr;
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static Gdiplus::Color GdiColor(COLORREF color, BYTE alpha = 255) {
    return Gdiplus::Color(alpha, GetRValue(color), GetGValue(color), GetBValue(color));
}

static bool DrawQqAvatarImage(HDC dc, RECT rc, const std::vector<BYTE>& bytes) {
    if (bytes.empty()) return false;
    HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, bytes.size());
    if (!memory) return false;
    void* ptr = GlobalLock(memory);
    if (!ptr) {
        GlobalFree(memory);
        return false;
    }
    CopyMemory(ptr, bytes.data(), bytes.size());
    GlobalUnlock(memory);

    IStream* stream = nullptr;
    if (FAILED(CreateStreamOnHGlobal(memory, TRUE, &stream)) || !stream) {
        GlobalFree(memory);
        return false;
    }

    Gdiplus::Bitmap bitmap(stream);
    bool ok = bitmap.GetLastStatus() == Gdiplus::Ok && bitmap.GetWidth() > 0 && bitmap.GetHeight() > 0;
    if (ok) {
        Gdiplus::Graphics graphics(dc);
        graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        graphics.SetInterpolationMode(Gdiplus::InterpolationModeHighQualityBicubic);
        graphics.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHalf);

        Gdiplus::GraphicsPath clipPath;
        Gdiplus::Rect dest(rc.left + 1, rc.top + 1, rc.right - rc.left - 2, rc.bottom - rc.top - 2);
        clipPath.AddEllipse(dest);
        graphics.SetClip(&clipPath);

        UINT bw = bitmap.GetWidth();
        UINT bh = bitmap.GetHeight();
        UINT side = std::min(bw, bh);
        UINT sx = (bw - side) / 2;
        UINT sy = (bh - side) / 2;
        ok = graphics.DrawImage(&bitmap, dest, sx, sy, side, side, Gdiplus::UnitPixel) == Gdiplus::Ok;
        graphics.ResetClip();
    }
    stream->Release();
    return ok;
}

static void DrawQqAvatarControl(HWND hwnd, HDC dc) {
    RECT client{};
    GetClientRect(hwnd, &client);
    FillRect(dc, &client, g_cardBrush ? g_cardBrush : (HBRUSH)(COLOR_WINDOW + 1));

    int w = client.right - client.left;
    int h = client.bottom - client.top;
    int size = std::max(20, std::min(w, h) - 2);
    RECT avatar{
        client.left + (w - size) / 2,
        client.top + (h - size) / 2,
        client.left + (w - size) / 2 + size,
        client.top + (h - size) / 2 + size
    };

    Gdiplus::Rect ellipse(avatar.left, avatar.top, avatar.right - avatar.left, avatar.bottom - avatar.top);
    {
        Gdiplus::Graphics graphics(dc);
        graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        Gdiplus::SolidBrush bg(g_app.mentionAvatarLoading ? GdiColor(RGB(230, 242, 255)) : GdiColor(C_CONTROL));
        graphics.FillEllipse(&bg, ellipse);
    }

    bool drewImage = !g_app.mentionAvatarBytes.empty() && DrawQqAvatarImage(dc, avatar, g_app.mentionAvatarBytes);
    {
        Gdiplus::Graphics graphics(dc);
        graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        Gdiplus::Pen border(drewImage ? GdiColor(RGB(210, 210, 216)) : GdiColor(C_BORDER), 1.0f);
        graphics.DrawEllipse(&border, ellipse);
    }

    if (!drewImage && (g_app.mentionAvatarLoading || g_app.mentionAvatarFailed)) {
        const wchar_t* text = g_app.mentionAvatarLoading ? L"..." : L"?";
        DrawCenteredText(dc, avatar, text, C_MUTED);
    }
}

static LRESULT CALLBACK AvatarWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(hwnd, &ps);
        DrawQqAvatarControl(hwnd, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return TRUE;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static void CloseNapcatQrWindow() {
    if (g_app.napcatQrWindow && IsWindow(g_app.napcatQrWindow)) {
        HWND qr = g_app.napcatQrWindow;
        g_app.napcatQrWindow = nullptr;
        DestroyWindow(qr);
    }
    g_app.napcatQrVisible = false;
    InvalidateNapcatQrCard();
}

static void ShowNapcatQrWindow() {
    g_app.napcatQrVisible = true;
    if (g_app.napcatQrWindow && IsWindow(g_app.napcatQrWindow)) {
        ShowWindow(g_app.napcatQrWindow, SW_SHOWNORMAL);
        SetForegroundWindow(g_app.napcatQrWindow);
        InvalidateRect(g_app.napcatQrWindow, nullptr, TRUE);
        InvalidateNapcatQrCard();
        return;
    }

    RECT mainRc{};
    GetWindowRect(g_app.hwnd, &mainRc);
    int x = mainRc.right + 12;
    int y = mainRc.top + 120;
    int screenW = GetSystemMetrics(SM_CXSCREEN);
    if (x + 340 > screenW) x = mainRc.left + 90;

    g_app.napcatQrWindow = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, L"LinyuKouziQr",
        L"NapCat 扫码登录", WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU,
        x, y, 340, 430, g_app.hwnd, nullptr, GetModuleHandleW(nullptr), nullptr);
    if (g_app.napcatQrWindow) {
        ShowWindow(g_app.napcatQrWindow, SW_SHOWNORMAL);
        UpdateWindow(g_app.napcatQrWindow);
    }
    InvalidateNapcatQrCard();
}

static HWND MakeGroup(HWND parent, const wchar_t* text, int x, int y, int w, int h) {
    return CreateWindowW(L"STATIC", text, WS_CHILD | WS_VISIBLE, x + 18, y + 8, w - 36, 22, parent, nullptr, nullptr, nullptr);
}

static HWND MakeEdit(HWND parent, int id, const wchar_t* text, int x, int y, int w, int h) {
    HWND hwnd = CreateWindowExW(0, L"EDIT", text, WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, x + 8, y + 5, w - 16, 22, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    SendMessageW(hwnd, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
    return hwnd;
}

static HWND MakePasswordEdit(HWND parent, int id, const wchar_t* text, int x, int y, int w, int h) {
    HWND hwnd = CreateWindowExW(0, L"EDIT", text, WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL | ES_PASSWORD, x + 8, y + 5, w - 16, 22, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    SendMessageW(hwnd, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
    SendMessageW(hwnd, EM_SETPASSWORDCHAR, L'*', 0);
    return hwnd;
}

static HWND MakeMultiEdit(HWND parent, int id, const wchar_t* text, int x, int y, int w, int h) {
    HWND hwnd = CreateWindowExW(0, L"EDIT", text,
        WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | WS_VSCROLL,
        x + 8, y + 8, w - 16, h - 16, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    SendMessageW(hwnd, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
    return hwnd;
}

static HWND MakeLogEdit(HWND parent, int id, int x, int y, int w, int h) {
    const wchar_t* className = L"EDIT";
    g_app.napcatLogRich = false;
    if (!g_richeditModule) g_richeditModule = LoadLibraryW(L"Msftedit.dll");
    if (g_richeditModule) {
        className = MSFTEDIT_CLASS;
        g_app.napcatLogRich = true;
    }
    HWND hwnd = CreateWindowExW(WS_EX_CLIENTEDGE, className, L"",
        WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
        x + 8, y + 8, w - 16, h - 16, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    SendMessageW(hwnd, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(10, 10));
    if (g_app.napcatLogRich) {
        SendMessageW(hwnd, EM_SETBKGNDCOLOR, 0, C_CONTROL);
    }
    return hwnd;
}

static HWND MakeAvatar(HWND parent, int id, int x, int y, int size) {
    return CreateWindowW(L"LinyuKouziAvatar", L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS,
        x, y, size, size, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
}

static HWND MakeButton(HWND parent, int id, const wchar_t* text, int x, int y, int w, int h) {
    return CreateWindowW(L"BUTTON", text, WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_OWNERDRAW, x, y, w, h, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
}

static HWND MakePopupButton(HWND parent, int id, const wchar_t* text, int x, int y, int w) {
    return CreateWindowW(L"BUTTON", text, WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_OWNERDRAW, x, y, w, 32, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
}

static HWND MakeCheck(HWND parent, int id, const wchar_t* text, int x, int y, int w, int h, bool checked) {
    SetSwitchState(id, checked);
    HWND hwnd = CreateWindowW(L"BUTTON", text, WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW, x, y, w, h, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    SetWindowSubclass(hwnd, SwitchSubclassProc, static_cast<UINT_PTR>(id), 0);
    return hwnd;
}

static HWND MakeCombo(HWND parent, int id, int x, int y, int w, const std::vector<const wchar_t*>& items, int selected) {
    HWND hwnd = CreateWindowW(L"COMBOBOX", L"", WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST, x, y, w, 180, parent, (HMENU)(intptr_t)id, nullptr, nullptr);
    for (auto* item : items) SendMessageW(hwnd, CB_ADDSTRING, 0, (LPARAM)item);
    SendMessageW(hwnd, CB_SETCURSEL, selected, 0);
    SendMessageW(hwnd, CB_SETITEMHEIGHT, (WPARAM)-1, 28);
    SendMessageW(hwnd, CB_SETITEMHEIGHT, 0, 28);
    return hwnd;
}

static HWND TrackPage(HWND hwnd, int page) {
    if (page == 0) g_app.sendPageControls.push_back(hwnd);
    else if (page == 1) g_app.aiPageControls.push_back(hwnd);
    else g_app.napcatPageControls.push_back(hwnd);
    return hwnd;
}

static void ShowPageControls(const std::vector<HWND>& controls, bool visible) {
    for (HWND ctl : controls) {
        if (ctl) {
            ShowWindow(ctl, visible ? SW_SHOW : SW_HIDE);
            EnableWindow(ctl, visible ? TRUE : FALSE);
        }
    }
}

static void SetActivePage(int page) {
    (void)page;
    g_app.activePage = 0;
    ShowPageControls(g_app.sendPageControls, g_app.activePage == 0);
    ShowPageControls(g_app.aiPageControls, g_app.activePage == 1);
    ShowPageControls(g_app.napcatPageControls, g_app.activePage == 2);
    HWND send = GetDlgItem(g_app.hwnd, ID_PAGE_SEND);
    HWND ai = GetDlgItem(g_app.hwnd, ID_PAGE_AI);
    HWND napcat = GetDlgItem(g_app.hwnd, ID_PAGE_NAPCAT);
    if (send) InvalidateRect(send, nullptr, TRUE);
    if (ai) InvalidateRect(ai, nullptr, TRUE);
    if (napcat) InvalidateRect(napcat, nullptr, TRUE);
    if (g_app.activePage != 2 && g_app.napcatLogEdit) ShowWindow(g_app.napcatLogEdit, SW_HIDE);
    if (g_app.hwnd) RedrawWindow(g_app.hwnd, nullptr, nullptr, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW);
}

static void ShowPreviewDialog(HWND parent, const std::wstring& preview) {
    HWND dlg = CreateWindowExW(WS_EX_DLGMODALFRAME, L"STATIC", L"发送前预览", WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
        CW_USEDEFAULT, CW_USEDEFAULT, 780, 500, parent, nullptr, nullptr, nullptr);
    HWND edit = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", preview.c_str(),
        WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
        12, 12, 740, 390, dlg, nullptr, nullptr, nullptr);
    SendMessageW(edit, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
    HWND ok = MakeButton(dlg, IDOK, L"关闭", 660, 415, 92, 30);
    SendMessageW(ok, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
}
