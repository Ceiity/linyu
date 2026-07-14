// INI 配置读写、默认配置、保存/加载/重置配置
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static std::wstring IniReadString(const wchar_t* key, const std::wstring& fallback = L"") {
    wchar_t buf[2048]{};
    GetPrivateProfileStringW(L"settings", key, fallback.c_str(), buf, 2048, ConfigPath().c_str());
    return buf;
}

static int IniReadInt(const wchar_t* key, int fallback) {
    return GetPrivateProfileIntW(L"settings", key, fallback, ConfigPath().c_str());
}

static bool IniReadBool(const wchar_t* key, bool fallback) {
    return IniReadInt(key, fallback ? 1 : 0) != 0;
}

static void IniWriteString(const wchar_t* key, const std::wstring& value) {
    WritePrivateProfileStringW(L"settings", key, value.c_str(), ConfigPath().c_str());
}

static void IniWriteInt(const wchar_t* key, int value) {
    IniWriteString(key, std::to_wstring(value));
}

static void IniWriteBool(const wchar_t* key, bool value) {
    IniWriteInt(key, value ? 1 : 0);
}

static std::wstring DefaultQqPath();

static void ApplyDefaultConfigToUi() {
    if (!g_app.pathEdit) return;
    g_applyingConfig = true;
    SetWindowTextW(g_app.pathEdit, L"");
    if (g_app.mentionQqEdit) SetWindowTextW(g_app.mentionQqEdit, L"");
    SetWindowTextW(g_app.aiApiKeyEdit, L"");
    SetWindowTextW(g_app.aiPersonaEdit, L"");
    SetWindowTextW(g_app.aiPromptEdit, L"");
    SetWindowTextW(g_app.aiCountEdit, L"10");
    SetWindowTextW(g_app.napcatUrlEdit, L"ws://127.0.0.1:3001");
    SetWindowTextW(g_app.napcatTokenEdit, L"");
    if (g_app.napcatQqPathEdit) SetWindowTextW(g_app.napcatQqPathEdit, DefaultQqPath().c_str());
    SetWindowTextW(g_app.keyDelayEdit, L"0.012");
    SetWindowTextW(g_app.commitDelayEdit, L"0.07");
    SetWindowTextW(g_app.lineDelayEdit, L"0.08");
    SetWindowTextW(g_app.pauseChanceEdit, L"0");
    SetWindowTextW(g_app.pauseMinEdit, L"0.05");
    SetWindowTextW(g_app.pauseMaxEdit, L"0.12");
    if (g_app.countdownEdit) SetWindowTextW(g_app.countdownEdit, L"5");

    g_app.inputModeSel = 0;
    g_app.inputLayoutSel = FindInputLayoutByHkl(GetKeyboardLayout(0));
    g_app.chunkModeSel = 1;
    g_app.enterModeSel = 0;
    g_app.librarySel = -1;
    g_app.mentionModeSel = 0;
    g_app.activePage = 0;
    SetSwitchState(ID_PREVIEW_BEFORE, false);
    SetSwitchState(ID_SOUND, false);
    SetSwitchState(ID_HUMANIZE, true);
    SetSwitchState(ID_CORRECTION_EFFECT, true);
    SetSwitchState(ID_CHECK_FOREGROUND, true);
    SetSwitchState(ID_NAPCAT_USE_CONTEXT, true);
    SetSwitchState(ID_NAPCAT_ONLY_AT, false);
    g_app.lastNapcatText.clear();
    g_app.lastNapcatRaw.clear();
    g_app.lastNapcatTick = 0;
    if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, L"NapCat 未监听。");
    g_applyingConfig = false;
    UpdatePopupTexts();
    RefreshQqAvatarPreviewFromEdit();
}

static void SaveConfig() {
    if (!g_app.pathEdit || !g_app.keyDelayEdit || !g_app.inputMode) return;
    IniWriteString(L"path", GetWindowTextString(g_app.pathEdit));
    if (g_app.mentionQqEdit) IniWriteString(L"mentionQq", GetWindowTextString(g_app.mentionQqEdit));
    IniWriteString(L"deepseekApiKey", GetWindowTextString(g_app.aiApiKeyEdit));
    IniWriteString(L"aiPersona", GetWindowTextString(g_app.aiPersonaEdit));
    IniWriteString(L"aiPrompt", GetWindowTextString(g_app.aiPromptEdit));
    IniWriteString(L"aiCount", GetWindowTextString(g_app.aiCountEdit));
    IniWriteString(L"napcatUrl", GetWindowTextString(g_app.napcatUrlEdit));
    IniWriteString(L"napcatToken", GetWindowTextString(g_app.napcatTokenEdit));
    if (g_app.napcatQqPathEdit) IniWriteString(L"napcatQqPath", GetWindowTextString(g_app.napcatQqPathEdit));
    IniWriteString(L"keyDelay", GetWindowTextString(g_app.keyDelayEdit));
    IniWriteString(L"commitDelay", GetWindowTextString(g_app.commitDelayEdit));
    IniWriteString(L"lineDelay", GetWindowTextString(g_app.lineDelayEdit));
    IniWriteString(L"pauseChance", GetWindowTextString(g_app.pauseChanceEdit));
    IniWriteString(L"pauseMin", GetWindowTextString(g_app.pauseMinEdit));
    IniWriteString(L"pauseMax", GetWindowTextString(g_app.pauseMaxEdit));
    if (g_app.countdownEdit) IniWriteString(L"countdown", GetWindowTextString(g_app.countdownEdit));

    IniWriteInt(L"inputMode", g_app.inputModeSel);
    IniWriteInt(L"inputLayout", g_app.inputLayoutSel);
    if (g_app.inputLayoutSel >= 0 && g_app.inputLayoutSel < static_cast<int>(g_inputLayouts.size())) {
        IniWriteString(L"inputLayoutKlid", g_inputLayouts[g_app.inputLayoutSel].klid);
    }
    IniWriteInt(L"chunkMode", g_app.chunkModeSel);
    IniWriteInt(L"enterMode", g_app.enterModeSel);
    IniWriteInt(L"librarySel", g_app.librarySel);
    IniWriteInt(L"mentionMode", g_app.mentionModeSel);
    IniWriteInt(L"activePage", 0);
    IniWriteBool(L"previewBefore", g_app.previewBeforeChecked);
    IniWriteBool(L"sound", g_app.soundChecked);
    IniWriteBool(L"humanize", g_app.humanizeChecked);
    IniWriteBool(L"correctionEffect", g_app.correctionEffectChecked);
    IniWriteBool(L"checkForeground", g_app.checkForegroundChecked);
    IniWriteBool(L"napcatUseContext", g_app.napcatUseContextChecked);
    IniWriteBool(L"napcatOnlyAt", g_app.napcatOnlyAtChecked);
}

static void LoadSavedConfig() {
    if (GetFileAttributesW(ConfigPath().c_str()) == INVALID_FILE_ATTRIBUTES) {
        ApplyDefaultConfigToUi();
        return;
    }
    g_applyingConfig = true;
    SetWindowTextW(g_app.pathEdit, IniReadString(L"path").c_str());
    if (g_app.mentionQqEdit) SetWindowTextW(g_app.mentionQqEdit, IniReadString(L"mentionQq").c_str());
    SetWindowTextW(g_app.aiApiKeyEdit, IniReadString(L"deepseekApiKey").c_str());
    SetWindowTextW(g_app.aiPersonaEdit, IniReadString(L"aiPersona").c_str());
    SetWindowTextW(g_app.aiPromptEdit, IniReadString(L"aiPrompt").c_str());
    SetWindowTextW(g_app.aiCountEdit, IniReadString(L"aiCount", L"10").c_str());
    SetWindowTextW(g_app.napcatUrlEdit, IniReadString(L"napcatUrl", L"ws://127.0.0.1:3001").c_str());
    SetWindowTextW(g_app.napcatTokenEdit, IniReadString(L"napcatToken").c_str());
    if (g_app.napcatQqPathEdit) SetWindowTextW(g_app.napcatQqPathEdit, IniReadString(L"napcatQqPath", DefaultQqPath()).c_str());
    SetWindowTextW(g_app.keyDelayEdit, IniReadString(L"keyDelay", L"0.012").c_str());
    SetWindowTextW(g_app.commitDelayEdit, IniReadString(L"commitDelay", L"0.07").c_str());
    SetWindowTextW(g_app.lineDelayEdit, IniReadString(L"lineDelay", L"0.08").c_str());
    SetWindowTextW(g_app.pauseChanceEdit, IniReadString(L"pauseChance", L"0").c_str());
    SetWindowTextW(g_app.pauseMinEdit, IniReadString(L"pauseMin", L"0.05").c_str());
    SetWindowTextW(g_app.pauseMaxEdit, IniReadString(L"pauseMax", L"0.12").c_str());
    if (g_app.countdownEdit) SetWindowTextW(g_app.countdownEdit, IniReadString(L"countdown", L"5").c_str());

    g_app.inputModeSel = std::clamp(IniReadInt(L"inputMode", 0), 0, 2);
    g_app.chunkModeSel = std::clamp(IniReadInt(L"chunkMode", 1), 0, 2);
    g_app.enterModeSel = std::clamp(IniReadInt(L"enterMode", 0), 0, 2);
    g_app.librarySel = IniReadInt(L"librarySel", -1);
    if (!g_textLibraries.empty()) g_app.librarySel = std::clamp(g_app.librarySel, 0, static_cast<int>(g_textLibraries.size()) - 1);
    else g_app.librarySel = -1;
    if (g_app.librarySel >= 0 && g_app.librarySel < static_cast<int>(g_textLibraries.size())) {
        SetWindowTextW(g_app.pathEdit, g_textLibraries[g_app.librarySel].path.c_str());
    }
    g_app.mentionModeSel = std::clamp(IniReadInt(L"mentionMode", 0), 0, 4);
    if (g_app.mentionModeSel == 0 && g_app.mentionQqEdit) SetWindowTextW(g_app.mentionQqEdit, L"");
    g_app.activePage = 0;
    int layoutSel = FindInputLayoutByKlid(IniReadString(L"inputLayoutKlid"));
    if (layoutSel < 0) layoutSel = IniReadInt(L"inputLayout", g_app.inputLayoutSel);
    if (!g_inputLayouts.empty()) layoutSel = std::clamp(layoutSel, 0, static_cast<int>(g_inputLayouts.size()) - 1);
    else layoutSel = 0;
    g_app.inputLayoutSel = layoutSel;

    SetSwitchState(ID_PREVIEW_BEFORE, IniReadBool(L"previewBefore", false));
    SetSwitchState(ID_SOUND, IniReadBool(L"sound", false));
    SetSwitchState(ID_HUMANIZE, IniReadBool(L"humanize", true));
    SetSwitchState(ID_CORRECTION_EFFECT, IniReadBool(L"correctionEffect", true));
    SetSwitchState(ID_CHECK_FOREGROUND, IniReadBool(L"checkForeground", true));
    SetSwitchState(ID_NAPCAT_USE_CONTEXT, IniReadBool(L"napcatUseContext", true));
    SetSwitchState(ID_NAPCAT_ONLY_AT, IniReadBool(L"napcatOnlyAt", false));
    if (g_app.napcatStatus) SetWindowTextW(g_app.napcatStatus, L"NapCat 未监听。");
    g_applyingConfig = false;
    UpdatePopupTexts();
    RefreshQqAvatarPreviewFromEdit();
}

static void ResetConfig() {
    if (MessageBoxW(g_app.hwnd, L"恢复默认配置？文本路径会清空，机械键盘音会关闭。", APP_TITLE, MB_OKCANCEL | MB_ICONQUESTION) != IDOK) {
        return;
    }
    ApplyDefaultConfigToUi();
    SetActivePage(g_app.activePage);
    DeleteFileW(ConfigPath().c_str());
    SaveConfig();
    SetWindowTextW(g_app.status, L"配置已重置。");
}
