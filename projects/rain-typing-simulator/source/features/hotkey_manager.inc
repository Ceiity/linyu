// Hotkey manager - hide window, taskbar toggle, and background mode

#ifndef FEATURES_HOTKEY_MANAGER_INC
#define FEATURES_HOTKEY_MANAGER_INC

#include <windows.h>
#include <shellapi.h>

static bool g_hotkeyHiddenWindow = false;
static bool g_hotkeyHiddenTaskbar = false;

#define HOTKEY_ID_F2  2001
#define HOTKEY_ID_F3  2002
#define HOTKEY_ID_F4  2003

static void RegisterStealthHotkeys(HWND hwnd) {
    RegisterHotKey(hwnd, HOTKEY_ID_F2, MOD_NOREPEAT, VK_F2);
    RegisterHotKey(hwnd, HOTKEY_ID_F3, MOD_NOREPEAT, VK_F3);
    RegisterHotKey(hwnd, HOTKEY_ID_F4, MOD_NOREPEAT, VK_F4);
}

static void UnregisterStealthHotkeys(HWND hwnd) {
    UnregisterHotKey(hwnd, HOTKEY_ID_F2);
    UnregisterHotKey(hwnd, HOTKEY_ID_F3);
    UnregisterHotKey(hwnd, HOTKEY_ID_F4);
}

static void RemoveWindowFromTaskbar(HWND hwnd) {
    LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    ex &= ~WS_EX_APPWINDOW;
    ex |= WS_EX_TOOLWINDOW;
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
}

static void RestoreWindowToTaskbar(HWND hwnd) {
    LONG_PTR ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    ex &= ~WS_EX_TOOLWINDOW;
    ex |= WS_EX_APPWINDOW;
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex);
}

// F2 toggles window visibility. Press F2 again to restore.
static void ToggleF2HideWindow(HWND hwnd) {
    g_hotkeyHiddenWindow = !g_hotkeyHiddenWindow;
    if (g_hotkeyHiddenWindow) {
        if (g_app.status) SetWindowTextW(g_app.status, L"[F2] Window hidden. Press F2 again to restore.");
        ShowWindow(hwnd, SW_HIDE);
    } else {
        ShowWindow(hwnd, SW_SHOW);
        SetForegroundWindow(hwnd);
        if (g_app.status) SetWindowTextW(g_app.status, L"[F2] Window restored.");
    }
}

// F3 toggles taskbar visibility while keeping the window visible.
static void ToggleF3Taskbar(HWND hwnd) {
    g_hotkeyHiddenTaskbar = !g_hotkeyHiddenTaskbar;
    ShowWindow(hwnd, SW_HIDE);
    if (g_hotkeyHiddenTaskbar) {
        RemoveWindowFromTaskbar(hwnd);
    } else {
        RestoreWindowToTaskbar(hwnd);
    }
    ShowWindow(hwnd, SW_SHOW);
    SetForegroundWindow(hwnd);
    if (g_app.status) SetWindowTextW(g_app.status, g_hotkeyHiddenTaskbar ? L"[F3] Taskbar icon restored." : L"[F3] Taskbar icon restored.");
}

// F4 enters background mode: hide window and taskbar icon.
static void DoF4BackgroundMode(HWND hwnd) {
    if (g_app.status) SetWindowTextW(g_app.status, L"[F4] Background mode enabled. Press F2 to restore.");
    g_hotkeyHiddenWindow = true;
    g_hotkeyHiddenTaskbar = true;
    RemoveWindowFromTaskbar(hwnd);
    ShowWindow(hwnd, SW_HIDE);
}

static void HandleStealthHotkey(HWND hwnd, WPARAM wParam) {
    switch (LOWORD(wParam)) {
    case HOTKEY_ID_F2: ToggleF2HideWindow(hwnd); break;
    case HOTKEY_ID_F3: ToggleF3Taskbar(hwnd); break;
    case HOTKEY_ID_F4: DoF4BackgroundMode(hwnd); break;
    }
}

static bool IsServiceMode() {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return false;
    bool svc = false;
    for (int i = 1; i < argc; ++i) {
        if (wcscmp(argv[i], L"--service") == 0) { svc = true; break; }
    }
    LocalFree(argv);
    return svc;
}

#endif
