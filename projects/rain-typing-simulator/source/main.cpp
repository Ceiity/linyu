#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <richedit.h>
#include <shellapi.h>
#include <psapi.h>
#include <mmsystem.h>
#include <dwmapi.h>
#include <winhttp.h>
#include <gdiplus.h>
#include <objidl.h>
#include <iphlpapi.h>
#include <imm.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <cwctype>

#include "pinyin_map.hpp"

#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "gdiplus.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "imm32.lib")

// 第一阶段结构重构说明：
// 这些 .inc 文件按原 main.cpp 的代码顺序包含，仍然组成同一个编译单元。
// 好处是：保留所有 static 函数、全局状态和原行为，同时把 4500+ 行拆进分类文件夹。
// 后续第二阶段再慢慢把 .inc 升级成真正的 .cpp/.h 模块。
#include "core/app_state.inc"
#include "utils/system_paths_input.inc"
#include "features/sound/keyboard_sound.inc"
#include "utils/text_json_helpers.inc"
#include "network/http_ws_ai.inc"
#include "sender/text_sender.inc"
#include "ui/ui_drawing_controls.inc"
#include "features/hotkey_manager.inc"
#include "features/library_sender.inc"
#include "config/app_config.inc"
#include "features/ai/ai_generation.inc"
#include "features/napcat/napcat_manager.inc"
#include "ui/window_proc.inc"

int APIENTRY wWinMain(HINSTANCE hInstance, HINSTANCE, LPWSTR, int nCmdShow) {
    INITCOMMONCONTROLSEX icc{ sizeof(icc), ICC_STANDARD_CLASSES };
    InitCommonControlsEx(&icc);
    Gdiplus::GdiplusStartupInput gdiplusInput;
    Gdiplus::GdiplusStartup(&g_gdiplusToken, &gdiplusInput, nullptr);

    WNDCLASSW wc{};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = L"LinyuKouziCpp";
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hIcon = LoadIconW(hInstance, MAKEINTRESOURCEW(1));
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassW(&wc);

    WNDCLASSW qrWc{};
    qrWc.lpfnWndProc = QrWndProc;
    qrWc.hInstance = hInstance;
    qrWc.lpszClassName = L"LinyuKouziQr";
    qrWc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    qrWc.hIcon = LoadIconW(hInstance, MAKEINTRESOURCEW(1));
    qrWc.hbrBackground = g_bgBrush ? g_bgBrush : (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassW(&qrWc);

    WNDCLASSW avatarWc{};
    avatarWc.lpfnWndProc = AvatarWndProc;
    avatarWc.hInstance = hInstance;
    avatarWc.lpszClassName = L"LinyuKouziAvatar";
    avatarWc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    avatarWc.hbrBackground = nullptr;
    RegisterClassW(&avatarWc);

    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, APP_TITLE,
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_CLIPCHILDREN,
        CW_USEDEFAULT, CW_USEDEFAULT, 760, 1020,
        nullptr, nullptr, hInstance, nullptr);

    // --service 模式：普通后台启动；不做进程伪装，不规避任务管理器。
    if (IsServiceMode()) {
        ShowWindow(hwnd, SW_HIDE);
        LONG_PTR exStyle = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        exStyle &= ~WS_EX_APPWINDOW;
        exStyle |= WS_EX_TOOLWINDOW;
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, exStyle);
    } else {
        ShowWindow(hwnd, nCmdShow);
    }
    UpdateWindow(hwnd);

    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
