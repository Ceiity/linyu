// 核心常量、控件 ID、Settings、AppState、全局状态、基础 UI 常量
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static const wchar_t* APP_TITLE = L"淋雨";

enum ControlId {
    ID_PATH = 1001,
    ID_BROWSE,
    ID_PREVIEW,
    ID_STOP,
    ID_START,
    ID_CONTINUE_SEND,
    ID_RESET_CONFIG,
    ID_PAGE_SEND,
    ID_PAGE_AI,
    ID_PAGE_NAPCAT,
    ID_AI_GENERATE,
    ID_AI_API_KEY,
    ID_AI_PERSONA,
    ID_AI_PROMPT,
    ID_AI_COUNT,
    ID_AI_START,
    ID_NAPCAT_URL,
    ID_NAPCAT_TOKEN,
    ID_NAPCAT_TOGGLE,
    ID_NAPCAT_USE_CONTEXT,
    ID_NAPCAT_ONLY_AT,
    ID_NAPCAT_QQ_PATH,
    ID_NAPCAT_INSTALL,
    ID_NAPCAT_START,
    ID_NAPCAT_WEBUI,
    ID_NAPCAT_CHECK,
    ID_NAPCAT_QR,
    ID_NAPCAT_LOG,
    ID_LIBRARY_SELECT,
    ID_LIBRARY_ADD,
    ID_LIBRARY_REMOVE,
    ID_LIBRARY_DROP_SELECT,
    ID_MENTION_AVATAR,
    ID_MENTION_QQ,
    ID_MENTION_MODE,
    ID_KEY_DELAY,
    ID_COMMIT_DELAY,
    ID_LINE_DELAY,
    ID_PAUSE_CHANCE,
    ID_PAUSE_MIN,
    ID_PAUSE_MAX,
    ID_COUNTDOWN,
    ID_INPUT_MODE,
    ID_INPUT_LAYOUT,
    ID_CHUNK_MODE,
    ID_ENTER_MODE,
    ID_HUMANIZE,
    ID_PREVIEW_BEFORE,
    ID_SOUND,
    ID_CORRECTION_EFFECT,
    ID_CHECK_FOREGROUND,
    WM_STATUS = WM_APP + 1,
    WM_FAILED = WM_APP + 2,
    WM_AI_DONE = WM_APP + 3,
    WM_AI_FAILED = WM_APP + 4,
    WM_NAPCAT_STATUS = WM_APP + 5,
    WM_NAPCAT_EVENT = WM_APP + 6,
    WM_QQ_AVATAR_DONE = WM_APP + 7,
};

struct InputLayoutInfo {
    HKL hkl{};
    std::wstring klid;
    std::wstring name;
};

struct Settings {
    double keyDelay = 0.012;
    double commitDelay = 0.07;
    double lineDelay = 0.08;
    double pauseChance = 0.0;
    double pauseMin = 0.05;
    double pauseMax = 0.12;
    int countdown = 5;
    int inputMode = 0; // 0 微软候选, 1 拼音输入法, 2 精确逐字
    HKL inputLayout{};
    std::wstring inputLayoutName;
    int chunkMode = 1; // 0 随机分词, 1 整句上屏, 2 逐字上屏
    int enterMode = 0; // 0 enter, 1 ctrl+enter, 2 none
    bool humanize = true;
    bool previewBefore = false;
    bool sound = false;
    bool correctionEffect = true;
    bool checkForeground = true;
    std::wstring mentionQq;
    int mentionMode = 0; // 0 off, 1 every line, 2 random lines, 3 natural spaced random, 4 direct @ only
};

struct AppState {
    HWND hwnd{};
    HWND pathEdit{};
    HWND librarySelect{};
    HWND mentionAvatar{};
    HWND mentionQqEdit{};
    HWND mentionMode{};
    HWND status{};
    HWND aiApiKeyEdit{};
    HWND aiPersonaEdit{};
    HWND aiPromptEdit{};
    HWND aiCountEdit{};
    HWND napcatUrlEdit{};
    HWND napcatTokenEdit{};
    HWND napcatToggleButton{};
    HWND napcatUseContext{};
    HWND napcatOnlyAt{};
    HWND napcatStatus{};
    HWND napcatQqPathEdit{};
    HWND napcatManagerStatus{};
    HWND napcatLogEdit{};
    HWND napcatQrWindow{};
    DWORD lastNapcatQrTick = 0;
    bool napcatLogRich = false;
    bool napcatQrVisible = false;
    bool napcatLoggedIn = false;
    bool napcatOneBotOnline = false;
    std::wstring displayedNapcatLog;
    HWND keyDelayEdit{};
    HWND commitDelayEdit{};
    HWND lineDelayEdit{};
    HWND pauseChanceEdit{};
    HWND pauseMinEdit{};
    HWND pauseMaxEdit{};
    HWND countdownEdit{};
    HWND inputMode{};
    HWND inputLayout{};
    HWND chunkMode{};
    HWND enterMode{};
    HWND humanize{};
    HWND previewBefore{};
    HWND sound{};
    HWND correctionEffect{};
    HWND checkForeground{};
    HWND titleLabel{};
    HWND subtitleLabel{};
    HFONT uiFont{};
    HFONT titleFont{};
    std::vector<HWND> sendPageControls;
    std::vector<HWND> aiPageControls;
    std::vector<HWND> napcatPageControls;
    int activePage = 0;
    int inputModeSel = 0;
    int inputLayoutSel = 0;
    int chunkModeSel = 1;
    int enterModeSel = 0;
    int librarySel = -1;
    int mentionModeSel = 0;
    bool humanizeChecked = true;
    bool previewBeforeChecked = false;
    bool soundChecked = false;
    bool correctionEffectChecked = true;
    bool checkForegroundChecked = true;
    bool napcatUseContextChecked = true;
    bool napcatOnlyAtChecked = false;
    bool aiStartAfterDone = false;
    std::wstring lastNapcatText;
    std::wstring lastNapcatRaw;
    std::wstring lastNapcatUserId;
    std::wstring lastNapcatGroupId;
    std::wstring lastNapcatName;
    std::wstring lastNapcatType;
    ULONGLONG lastNapcatTick = 0;
    ULONGLONG lastNapcatAutoListenTick = 0;
    DWORD lastNapcatLogTick = 0;
    UINT lastSwitchId = 0;
    DWORD lastSwitchTick = 0;
    UINT lastNapcatButtonId = 0;
    DWORD lastNapcatButtonTick = 0;
    std::wstring mentionAvatarQq;
    std::vector<BYTE> mentionAvatarBytes;
    UINT mentionAvatarSerial = 0;
    bool mentionAvatarLoading = false;
    bool mentionAvatarFailed = false;
    std::atomic_bool aiGenerating{false};
    std::atomic_bool napcatRunning{false};
    std::atomic_bool stop{false};
    std::atomic_bool running{false};
};

static AppState g_app;
static std::mt19937 g_rng{std::random_device{}()};
static std::vector<InputLayoutInfo> g_inputLayouts;
static HHOOK g_mouseHook = nullptr;
static std::atomic_uint g_avatarRequestSerial{0};
static bool g_mentionQqInternalChange = false;
static bool g_applyingConfig = false;

struct TextLibraryItem {
    std::wstring name;
    std::wstring path;
};

static std::vector<TextLibraryItem> g_textLibraries;

static bool* SwitchStatePtr(UINT id) {
    switch (id) {
    case ID_HUMANIZE: return &g_app.humanizeChecked;
    case ID_PREVIEW_BEFORE: return &g_app.previewBeforeChecked;
    case ID_SOUND: return &g_app.soundChecked;
    case ID_CORRECTION_EFFECT: return &g_app.correctionEffectChecked;
    case ID_CHECK_FOREGROUND: return &g_app.checkForegroundChecked;
    case ID_NAPCAT_USE_CONTEXT: return &g_app.napcatUseContextChecked;
    case ID_NAPCAT_ONLY_AT: return &g_app.napcatOnlyAtChecked;
    default: return nullptr;
    }
}

static bool GetSwitchState(UINT id) {
    bool* state = SwitchStatePtr(id);
    return state ? *state : false;
}

static void SetSwitchState(UINT id, bool checked) {
    bool* state = SwitchStatePtr(id);
    if (state) *state = checked;
    if (g_app.hwnd) {
        HWND ctl = GetDlgItem(g_app.hwnd, id);
        if (ctl) {
            InvalidateRect(ctl, nullptr, TRUE);
            UpdateWindow(ctl);
        }
    }
}

static void ToggleSwitch(HWND hwnd) {
    UINT id = static_cast<UINT>(GetDlgCtrlID(hwnd));
    SetFocus(hwnd);
    SetSwitchState(id, !GetSwitchState(id));
    g_app.lastSwitchId = id;
    g_app.lastSwitchTick = GetTickCount();
}

static bool IsNapcatActionButton(UINT id) {
    return id == ID_NAPCAT_INSTALL
        || id == ID_NAPCAT_START
        || id == ID_NAPCAT_WEBUI
        || id == ID_NAPCAT_CHECK
        || id == ID_NAPCAT_QR;
}

static void PostNapcatCommandId(UINT id, HWND source) {
    if (!IsNapcatActionButton(id)) return;
    DWORD now = GetTickCount();
    if (g_app.lastNapcatButtonId == id && now - g_app.lastNapcatButtonTick < 350) return;
    g_app.lastNapcatButtonId = id;
    g_app.lastNapcatButtonTick = now;
    HWND parent = g_app.hwnd ? g_app.hwnd : GetParent(source);
    if (parent) PostMessageW(parent, WM_COMMAND, MAKEWPARAM(id, BN_CLICKED), reinterpret_cast<LPARAM>(source));
}

static void PostNapcatAction(HWND button) {
    UINT id = static_cast<UINT>(GetDlgCtrlID(button));
    PostNapcatCommandId(id, button);
}

static UINT NapcatActionIdFromPoint(POINT pt) {
    if (g_app.activePage != 2) return 0;
    struct Hit { RECT rc; UINT id; };
    static const Hit hits[] = {
        { { 48, 214, 198, 252 }, ID_NAPCAT_INSTALL },
        { { 218, 214, 348, 252 }, ID_NAPCAT_START },
        { { 368, 214, 498, 252 }, ID_NAPCAT_WEBUI },
        { { 518, 214, 648, 252 }, ID_NAPCAT_CHECK },
        { { 48, 270, 178, 306 }, ID_NAPCAT_QR },
    };
    for (const auto& hit : hits) {
        if (PtInRect(&hit.rc, pt)) return hit.id;
    }
    return 0;
}

static LRESULT CALLBACK MainMouseHookProc(int code, WPARAM wParam, LPARAM lParam) {
    if (code >= 0 && wParam == WM_LBUTTONUP && g_app.hwnd && IsWindow(g_app.hwnd)) {
        auto* info = reinterpret_cast<MOUSEHOOKSTRUCT*>(lParam);
        POINT pt = info->pt;
        ScreenToClient(g_app.hwnd, &pt);
        UINT id = NapcatActionIdFromPoint(pt);
        if (id) {
            HWND source = GetDlgItem(g_app.hwnd, id);
            PostNapcatCommandId(id, source);
        }
    }
    return CallNextHookEx(g_mouseHook, code, wParam, lParam);
}

static LRESULT CALLBACK NapcatButtonSubclassProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam, UINT_PTR subclassId, DWORD_PTR) {
    switch (msg) {
    case WM_LBUTTONUP: {
        SendMessageW(hwnd, BM_SETSTATE, FALSE, 0);
        ReleaseCapture();
        POINT pt{ GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam) };
        RECT rc{};
        GetClientRect(hwnd, &rc);
        if (PtInRect(&rc, pt)) PostNapcatAction(hwnd);
        return 0;
    }
    case WM_KEYUP:
        if (wParam == VK_SPACE || wParam == VK_RETURN) {
            PostNapcatAction(hwnd);
            return 0;
        }
        break;
    case WM_NCDESTROY:
        RemoveWindowSubclass(hwnd, NapcatButtonSubclassProc, subclassId);
        break;
    }
    return DefSubclassProc(hwnd, msg, wParam, lParam);
}

static LRESULT CALLBACK SwitchSubclassProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam, UINT_PTR subclassId, DWORD_PTR) {
    switch (msg) {
    case WM_LBUTTONDOWN: {
        POINT pt{ static_cast<SHORT>(LOWORD(lParam)), static_cast<SHORT>(HIWORD(lParam)) };
        RECT rc{};
        GetClientRect(hwnd, &rc);
        if (PtInRect(&rc, pt)) {
            SetCapture(hwnd);
            ToggleSwitch(hwnd);
            return 0;
        }
        break;
    }
    case WM_LBUTTONUP:
        if (GetCapture() == hwnd) ReleaseCapture();
        return 0;
    case WM_LBUTTONDBLCLK:
        return 0;
    case WM_CANCELMODE:
        if (GetCapture() == hwnd) ReleaseCapture();
        break;
    case WM_KEYDOWN:
        if (wParam == VK_SPACE || wParam == VK_RETURN) {
            if ((lParam & 0x40000000) == 0) ToggleSwitch(hwnd);
            return 0;
        }
        break;
    case WM_KEYUP:
        if (wParam == VK_SPACE || wParam == VK_RETURN) return 0;
        break;
    case WM_NCDESTROY:
        RemoveWindowSubclass(hwnd, SwitchSubclassProc, subclassId);
        break;
    }
    return DefSubclassProc(hwnd, msg, wParam, lParam);
}

static constexpr COLORREF C_BG = RGB(245, 245, 247);
static constexpr COLORREF C_CARD = RGB(255, 255, 255);
static constexpr COLORREF C_CARD_2 = RGB(242, 242, 247);
static constexpr COLORREF C_BORDER = RGB(224, 224, 229);
static constexpr COLORREF C_TEXT = RGB(28, 28, 30);
static constexpr COLORREF C_MUTED = RGB(112, 112, 118);
static constexpr COLORREF C_ACCENT = RGB(0, 122, 255);
static constexpr COLORREF C_ACCENT_DARK = RGB(0, 90, 200);
static constexpr COLORREF C_DANGER = RGB(255, 59, 48);
static constexpr COLORREF C_WARNING = RGB(255, 184, 28);
static constexpr COLORREF C_WARNING_DARK = RGB(225, 150, 0);
static constexpr COLORREF C_CONTROL = RGB(248, 248, 250);
static constexpr int BASE_CLIENT_W = 744;
static constexpr int BASE_CLIENT_H = 981;
static constexpr int MIN_WINDOW_W = 620;
static constexpr int MIN_WINDOW_H = 780;

static HBRUSH g_bgBrush{};
static HBRUSH g_cardBrush{};
static HBRUSH g_controlBrush{};
static ULONG_PTR g_gdiplusToken = 0;
static HMODULE g_richeditModule = nullptr;

struct ChildBaseLayout {
    HWND hwnd{};
    RECT rect{};
};

static std::vector<ChildBaseLayout> g_childBaseLayouts;
static bool g_layoutCaptured = false;
