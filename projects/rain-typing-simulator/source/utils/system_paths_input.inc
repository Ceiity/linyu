// 程序路径、配置路径、输入法布局枚举与查找、短文本工具
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static std::wstring ExeDir() {
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    std::wstring s(path);
    auto pos = s.find_last_of(L"\\/");
    return pos == std::wstring::npos ? L"." : s.substr(0, pos);
}

static std::wstring ConfigDir() {
    wchar_t appData[MAX_PATH]{};
    DWORD len = GetEnvironmentVariableW(L"APPDATA", appData, MAX_PATH);
    std::wstring base = (len > 0 && len < MAX_PATH) ? std::wstring(appData) : ExeDir();
    std::wstring dir = base + L"\\淋雨扣字手";
    CreateDirectoryW(dir.c_str(), nullptr);
    return dir;
}

static std::wstring ConfigPath() {
    return ConfigDir() + L"\\settings.ini";
}

static std::wstring HklHex(HKL hkl) {
    wchar_t buf[24]{};
    swprintf(buf, 24, L"%08X", static_cast<unsigned int>(reinterpret_cast<uintptr_t>(hkl) & 0xffffffffu));
    return buf;
}

static std::wstring ReadRegString(HKEY root, const std::wstring& subkey, const wchar_t* valueName) {
    HKEY key{};
    if (RegOpenKeyExW(root, subkey.c_str(), 0, KEY_READ, &key) != ERROR_SUCCESS) return L"";
    wchar_t buf[512]{};
    DWORD type = 0;
    DWORD size = sizeof(buf);
    LONG ok = RegQueryValueExW(key, valueName, nullptr, &type, reinterpret_cast<LPBYTE>(buf), &size);
    RegCloseKey(key);
    if (ok != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) return L"";
    return buf;
}

static std::wstring LocaleDisplayName(HKL hkl) {
    LANGID lang = LOWORD(reinterpret_cast<uintptr_t>(hkl));
    wchar_t locale[LOCALE_NAME_MAX_LENGTH]{};
    if (!LCIDToLocaleName(MAKELCID(lang, SORT_DEFAULT), locale, LOCALE_NAME_MAX_LENGTH, 0)) return L"";
    wchar_t name[128]{};
    if (!GetLocaleInfoEx(locale, LOCALE_SLOCALIZEDDISPLAYNAME, name, 128)) return L"";
    return name;
}

static std::wstring LayoutRegistryName(const std::wstring& klid) {
    std::wstring subkey = L"SYSTEM\\CurrentControlSet\\Control\\Keyboard Layouts\\" + klid;
    std::wstring text = ReadRegString(HKEY_LOCAL_MACHINE, subkey, L"Layout Text");
    if (!text.empty()) return text;
    text = ReadRegString(HKEY_LOCAL_MACHINE, subkey, L"Layout Display Name");
    return text.empty() ? klid : text;
}

static int FindInputLayoutByKlid(const std::wstring& klid) {
    for (size_t i = 0; i < g_inputLayouts.size(); ++i) {
        if (_wcsicmp(g_inputLayouts[i].klid.c_str(), klid.c_str()) == 0) return static_cast<int>(i);
    }
    return -1;
}

static int FindInputLayoutByHkl(HKL hkl) {
    for (size_t i = 0; i < g_inputLayouts.size(); ++i) {
        if (g_inputLayouts[i].hkl == hkl) return static_cast<int>(i);
    }
    return 0;
}

static void LoadInputLayouts() {
    g_inputLayouts.clear();
    int count = GetKeyboardLayoutList(0, nullptr);
    std::vector<HKL> layouts(count > 0 ? count : 1);
    if (count > 0) {
        GetKeyboardLayoutList(count, layouts.data());
    } else {
        layouts[0] = GetKeyboardLayout(0);
    }

    HKL old = GetKeyboardLayout(0);
    for (HKL hkl : layouts) {
        if (!hkl) continue;
        ActivateKeyboardLayout(hkl, 0);
        wchar_t klidBuf[KL_NAMELENGTH]{};
        std::wstring klid = GetKeyboardLayoutNameW(klidBuf) ? std::wstring(klidBuf) : HklHex(hkl);
        if (FindInputLayoutByKlid(klid) >= 0) continue;

        std::wstring locale = LocaleDisplayName(hkl);
        std::wstring layout = LayoutRegistryName(klid);
        std::wstring name = locale.empty() ? layout : (locale + L" / " + layout);
        if (name.empty()) name = klid;
        g_inputLayouts.push_back({ hkl, klid, name });
    }
    if (old) ActivateKeyboardLayout(old, 0);
    if (g_inputLayouts.empty()) {
        HKL hkl = GetKeyboardLayout(0);
        g_inputLayouts.push_back({ hkl, HklHex(hkl), L"当前输入法" });
    }
    g_app.inputLayoutSel = FindInputLayoutByHkl(old);
}

static std::wstring ShortText(std::wstring text, size_t maxChars) {
    if (text.size() <= maxChars) return text;
    if (maxChars <= 1) return text.substr(0, maxChars);
    return text.substr(0, maxChars - 1) + L"…";
}
