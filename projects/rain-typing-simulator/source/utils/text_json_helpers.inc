// 文本读取、编码转换、字符串清理、JSON 简单解析、NapCat 日志文本规范化、UTF-8 文件写入
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

static std::wstring GetWindowTextString(HWND hwnd) {
    if (!hwnd) return L"";
    int len = GetWindowTextLengthW(hwnd);
    std::wstring value(len + 1, L'\0');
    GetWindowTextW(hwnd, value.data(), len + 1);
    value.resize(len);
    return value;
}

static void SetStatus(const std::wstring& text) {
    auto* copy = new std::wstring(text);
    PostMessageW(g_app.hwnd, WM_STATUS, 0, reinterpret_cast<LPARAM>(copy));
}

static void PostNapcatStatus(const std::wstring& text) {
    auto* copy = new std::wstring(text);
    PostMessageW(g_app.hwnd, WM_NAPCAT_STATUS, 0, reinterpret_cast<LPARAM>(copy));
}

static std::wstring Trim(std::wstring text);

static double ReadDouble(HWND edit, double fallback) {
    auto text = GetWindowTextString(edit);
    wchar_t* end = nullptr;
    double value = wcstod(text.c_str(), &end);
    return end == text.c_str() ? fallback : value;
}

static int ReadInt(HWND edit, int fallback) {
    auto text = GetWindowTextString(edit);
    wchar_t* end = nullptr;
    long value = wcstol(text.c_str(), &end, 10);
    return end == text.c_str() ? fallback : static_cast<int>(value);
}

static std::wstring DigitsOnly(const std::wstring& text) {
    std::wstring out;
    for (wchar_t ch : text) {
        if (iswdigit(ch)) out.push_back(ch);
    }
    return out;
}

static std::wstring ExtractQqNumber(std::wstring text) {
    text = Trim(text);
    std::wstring lower = text;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](wchar_t ch) {
        return static_cast<wchar_t>(towlower(ch));
    });
    const std::wstring key = L"dst_uin=";
    size_t pos = lower.find(key);
    if (pos != std::wstring::npos) {
        pos += key.size();
        std::wstring out;
        while (pos < text.size() && iswdigit(text[pos])) {
            out.push_back(text[pos++]);
        }
        if (!out.empty()) return out;
    }
    return DigitsOnly(text);
}

static Settings ReadSettings() {
    Settings s;
    s.keyDelay = std::max(0.006, ReadDouble(g_app.keyDelayEdit, s.keyDelay));
    s.commitDelay = std::max(0.02, ReadDouble(g_app.commitDelayEdit, s.commitDelay));
    s.lineDelay = std::max(0.0, ReadDouble(g_app.lineDelayEdit, s.lineDelay));
    s.pauseChance = std::clamp(ReadDouble(g_app.pauseChanceEdit, 0.0) / 100.0, 0.0, 1.0);
    s.pauseMin = std::max(0.0, ReadDouble(g_app.pauseMinEdit, s.pauseMin));
    s.pauseMax = std::max(s.pauseMin, ReadDouble(g_app.pauseMaxEdit, s.pauseMax));
    if (g_app.countdownEdit) s.countdown = std::max(1, ReadInt(g_app.countdownEdit, s.countdown));
    s.inputMode = g_app.inputModeSel;
    if (g_app.inputLayoutSel >= 0 && g_app.inputLayoutSel < static_cast<int>(g_inputLayouts.size())) {
        s.inputLayout = g_inputLayouts[g_app.inputLayoutSel].hkl;
        s.inputLayoutName = g_inputLayouts[g_app.inputLayoutSel].name;
    }
    s.chunkMode = g_app.chunkModeSel;
    s.enterMode = g_app.enterModeSel;
    s.humanize = g_app.humanizeChecked;
    s.previewBefore = g_app.previewBeforeChecked;
    s.sound = g_app.soundChecked;
    s.correctionEffect = g_app.correctionEffectChecked;
    s.checkForeground = g_app.checkForegroundChecked;
    s.mentionQq = ExtractQqNumber(GetWindowTextString(g_app.mentionQqEdit));
    s.mentionMode = std::clamp(g_app.mentionModeSel, 0, 4);
    if (s.mentionQq.empty()) s.mentionMode = 0;
    return s;
}

static std::wstring Utf8ToWide(const std::string& bytes) {
    int len = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    if (len <= 0) return {};
    std::wstring out(len, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes.data(), static_cast<int>(bytes.size()), out.data(), len);
    return out;
}

static std::wstring Utf8ToWideLossy(const std::string& bytes) {
    int len = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    if (len <= 0) return {};
    std::wstring out(len, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), out.data(), len);
    return out;
}

static std::string WideToUtf8(const std::wstring& text) {
    int len = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string out(len, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), len, nullptr, nullptr);
    return out;
}

static USHORT PortFromTcpTableValue(DWORD value) {
    return static_cast<USHORT>(((value & 0xff) << 8) | ((value >> 8) & 0xff));
}

static bool IsTcpPortListening(USHORT targetPort) {
    ULONG size = 0;
    if (GetTcpTable2(nullptr, &size, TRUE) == ERROR_INSUFFICIENT_BUFFER && size > 0) {
        std::vector<BYTE> buffer(size);
        auto* table = reinterpret_cast<PMIB_TCPTABLE2>(buffer.data());
        if (GetTcpTable2(table, &size, TRUE) == NO_ERROR) {
            for (DWORD i = 0; i < table->dwNumEntries; ++i) {
                if (table->table[i].dwState == MIB_TCP_STATE_LISTEN && PortFromTcpTableValue(table->table[i].dwLocalPort) == targetPort) {
                    return true;
                }
            }
        }
    }

    using GetTcp6Table2Fn = ULONG(WINAPI*)(PMIB_TCP6TABLE2, PULONG, BOOL);
    HMODULE iphlp = GetModuleHandleW(L"iphlpapi.dll");
    auto getTcp6Table2 = iphlp ? reinterpret_cast<GetTcp6Table2Fn>(GetProcAddress(iphlp, "GetTcp6Table2")) : nullptr;
    if (getTcp6Table2) {
        size = 0;
        if (getTcp6Table2(nullptr, &size, TRUE) == ERROR_INSUFFICIENT_BUFFER && size > 0) {
            std::vector<BYTE> buffer(size);
            auto* table = reinterpret_cast<PMIB_TCP6TABLE2>(buffer.data());
            if (getTcp6Table2(table, &size, TRUE) == NO_ERROR) {
                for (DWORD i = 0; i < table->dwNumEntries; ++i) {
                    if (table->table[i].State == MIB_TCP_STATE_LISTEN && PortFromTcpTableValue(table->table[i].dwLocalPort) == targetPort) {
                        return true;
                    }
                }
            }
        }
    }
    return false;
}

static std::wstring AcpToWide(const std::string& bytes) {
    int len = MultiByteToWideChar(CP_ACP, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
    if (len <= 0) return {};
    std::wstring out(len, L'\0');
    MultiByteToWideChar(CP_ACP, 0, bytes.data(), static_cast<int>(bytes.size()), out.data(), len);
    return out;
}

static std::string WideToCodePageBytes(const std::wstring& text, UINT codePage) {
    int len = WideCharToMultiByte(codePage, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string out(len, '\0');
    WideCharToMultiByte(codePage, 0, text.data(), static_cast<int>(text.size()), out.data(), len, nullptr, nullptr);
    return out;
}

static bool LooksLikeMojibake(const std::wstring& text) {
    static const wchar_t* marks[] = {
        L"浜", L"鐮", L"鈻", L"鍙", L"鎺", L"绉", L"杽", L"枅",
        L"宸", L"瀹", L"悜", L"佽", L"€", L"乁", L"淇濆瓨"
    };
    for (auto* mark : marks) {
        if (text.find(mark) != std::wstring::npos) return true;
    }
    return false;
}

static void ReplaceAll(std::wstring& text, const std::wstring& from, const std::wstring& to) {
    if (from.empty()) return;
    size_t pos = 0;
    while ((pos = text.find(from, pos)) != std::wstring::npos) {
        text.replace(pos, from.size(), to);
        pos += to.size();
    }
}

static std::wstring ApplyNapcatMojibakeDictionary(std::wstring text) {
    struct Pair { const wchar_t* from; const wchar_t* to; };
    static const Pair pairs[] = {
        { L"鎺ユ敹", L"接收" },
        { L"鍙戦€?", L"发送" },
        { L"鍙戦€", L"发送" },
        { L"缇よ亰", L"群聊" },
        { L"绉佽亰", L"私聊" },
        { L"娑堟伅", L"消息" },
        { L"缇ら噷", L"群里" },
        { L"鍙堣繋鏉ヤ簡", L"又迎来了" },
        { L"鏂版垚鍛橈紝", L"新成员，" },
        { L"鏂版垚鍛", L"新成员" },
        { L"娆㈣繋", L"欢迎" },
        { L"浣犱滑", L"你们" },
        { L"鐨勫姞鍏ワ紒", L"的加入！" },
        { L"鐨勫姞鍏", L"的加入" },
        { L"浜岀淮鐮佽В鐮乁RL", L"二维码解码URL" },
        { L"浜岀淮鐮佸凡淇濆瓨鍒?", L"二维码已保存到 " },
        { L"浜岀淮鐮佸凡淇濆瓨鍒", L"二维码已保存到" },
        { L"璇锋壂鎻", L"请扫描" },
        { L"鎵嬫満", L"手机" },
        { L"鎺堟潈", L"授权" },
        { L"鐧诲綍", L"登录" },
        { L"鎴戞兂", L"我想" },
        { L"鎴戠殑", L"我的" },
        { L"鐧介┈鐜嬪瓙", L"白马王子" },
        { L"鍦ㄥ摢閲岋紵", L"在哪里？" },
        { L"鍦ㄥ摢閲", L"在哪里" },
        { L"鎵ｅ瓧鎵", L"扣字手" },
        { L"闆嗗湴", L"集地" },
        { L"浠ュ悗涓嶈浜?", L"以后不说了" },
        { L"浠ュ悗涓嶈浜", L"以后不说了" },
        { L"鈶?", L"" },
        { L"锛?|", L"|" },
        { L"锛?", L"" },
    };
    for (const auto& pair : pairs) ReplaceAll(text, pair.from, pair.to);
    return text;
}

static int MojibakeScore(const std::wstring& text) {
    int score = 0;
    static const wchar_t noisyChars[] = {
        L'浜', L'鐮', L'鈻', L'鍙', L'鎺', L'绉', L'杽', L'枅',
        L'宸', L'瀹', L'佽', L'乁', L'锛', L'€', L'熷', L'嬫'
    };
    for (wchar_t ch : text) {
        for (wchar_t noisy : noisyChars) {
            if (ch == noisy) {
                score += 2;
                break;
            }
        }
        if (ch == 0xfffd) score += 4;
    }
    return score;
}

static std::wstring StripAnsiEscapes(const std::wstring& text) {
    std::wstring out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); ++i) {
        if (text[i] == 0x1b && i + 1 < text.size() && text[i + 1] == L'[') {
            i += 2;
            while (i < text.size() && !iswalpha(text[i])) ++i;
            continue;
        }
        out.push_back(text[i]);
    }
    return out;
}

static std::wstring RepairMojibakeLine(std::wstring line) {
    line = StripAnsiEscapes(line);
    line = ApplyNapcatMojibakeDictionary(line);
    if (!LooksLikeMojibake(line)) return line;

    // NapCat UTF-8 output can be decoded once as GBK/OEM by Windows PowerShell.
    // Re-encoding that mojibake with CP936 and decoding as UTF-8 recovers it.
    std::string bytes = WideToCodePageBytes(line, 936);
    std::wstring repaired = Utf8ToWide(bytes);
    if (repaired.empty()) repaired = Utf8ToWideLossy(bytes);
    if (repaired.empty()) {
        bytes = WideToCodePageBytes(line, CP_ACP);
        repaired = Utf8ToWide(bytes);
        if (repaired.empty()) repaired = Utf8ToWideLossy(bytes);
    }
    repaired = ApplyNapcatMojibakeDictionary(StripAnsiEscapes(repaired));
    if (repaired.empty()) return line;
    return MojibakeScore(repaired) <= MojibakeScore(line) ? repaired : line;
}

static std::wstring Trim(std::wstring text);

static std::wstring FirstClockText(const std::wstring& line) {
    for (size_t i = 0; i + 7 < line.size(); ++i) {
        if (iswdigit(line[i]) && iswdigit(line[i + 1]) && line[i + 2] == L':'
            && iswdigit(line[i + 3]) && iswdigit(line[i + 4]) && line[i + 5] == L':'
            && iswdigit(line[i + 6]) && iswdigit(line[i + 7])) {
            return line.substr(i, 8);
        }
    }
    return L"";
}

static std::wstring StripIdSuffix(std::wstring text) {
    text = Trim(text);
    if (!text.empty() && text.front() == L'[' && text.back() == L']') text = text.substr(1, text.size() - 2);
    size_t right = text.rfind(L')');
    size_t left = text.rfind(L'(');
    if (left != std::wstring::npos && right == text.size() - 1 && left < right) {
        bool allDigits = true;
        for (size_t i = left + 1; i < right; ++i) {
            if (!iswdigit(text[i])) {
                allDigits = false;
                break;
            }
        }
        if (allDigits) text = Trim(text.substr(0, left));
    }
    return text.empty() ? L"未知" : text;
}

static std::vector<std::wstring> ExtractBracketParts(const std::wstring& text, size_t* lastEnd) {
    std::vector<std::wstring> parts;
    size_t pos = 0;
    size_t endPos = 0;
    while (pos < text.size()) {
        size_t left = text.find(L'[', pos);
        if (left == std::wstring::npos) break;
        size_t right = text.find(L']', left + 1);
        if (right == std::wstring::npos) break;
        parts.push_back(text.substr(left + 1, right - left - 1));
        endPos = right + 1;
        pos = right + 1;
        while (pos < text.size() && iswspace(text[pos])) ++pos;
        if (pos < text.size() && text[pos] != L'[') break;
    }
    if (lastEnd) *lastEnd = endPos;
    return parts;
}

static bool IsMessageTypePart(const std::wstring& part) {
    return part.find(L"消息") != std::wstring::npos
        || part.find(L"Markdown") != std::wstring::npos
        || part.find(L"图片") != std::wstring::npos
        || part.find(L"语音") != std::wstring::npos
        || part.find(L"视频") != std::wstring::npos;
}

static std::wstring FormatNapcatChatRecordLine(const std::wstring& line) {
    size_t pos = line.find(L"接收 <-");
    bool incoming = true;
    size_t markerLen = 5;
    if (pos == std::wstring::npos) {
        pos = line.find(L"发送 ->");
        incoming = false;
    }
    if (pos == std::wstring::npos) return line;

    std::wstring rest = Trim(line.substr(pos + markerLen));
    size_t typeEnd = rest.find(L'[');
    std::wstring chatType = typeEnd == std::wstring::npos ? Trim(rest) : Trim(rest.substr(0, typeEnd));
    std::wstring afterType = typeEnd == std::wstring::npos ? L"" : rest.substr(typeEnd);
    size_t bracketEnd = 0;
    auto parts = ExtractBracketParts(afterType, &bracketEnd);
    std::wstring message = Trim(bracketEnd < afterType.size() ? afterType.substr(bracketEnd) : L"");

    std::wstring group;
    std::wstring sender;
    if (chatType.find(L"群聊") != std::wstring::npos) {
        if (!parts.empty()) group = StripIdSuffix(parts[0]);
        if (parts.size() >= 2) sender = StripIdSuffix(parts[1]);
        if (parts.size() >= 3 && IsMessageTypePart(parts[2]) && message.empty()) message = L"[" + StripIdSuffix(parts[2]) + L"]";
    } else {
        if (!parts.empty()) sender = StripIdSuffix(parts[0]);
        if (parts.size() >= 2 && IsMessageTypePart(parts[1]) && message.empty()) message = L"[" + StripIdSuffix(parts[1]) + L"]";
    }
    if (message.empty()) message = L"[非文本消息]";
    message = ShortText(message, 220);

    std::wstring out;
    std::wstring clock = FirstClockText(line);
    if (!clock.empty()) out += clock + L" ";
    out += incoming ? L"[接收]" : L"[发送]";
    out += L"[" + (chatType.empty() ? L"聊天" : chatType) + L"] ";
    if (!group.empty()) out += group + L" / ";
    out += (sender.empty() ? L"未知" : sender);
    out += L"：";
    out += message;
    return out;
}

static std::wstring NormalizeNapcatLogText(const std::wstring& text) {
    std::wstring out;
    std::wstring line;
    for (wchar_t ch : text) {
        if (ch == L'\r' || ch == L'\n') {
            out += FormatNapcatChatRecordLine(RepairMojibakeLine(line));
            out.push_back(ch);
            line.clear();
        } else {
            line.push_back(ch);
        }
    }
    if (!line.empty()) out += FormatNapcatChatRecordLine(RepairMojibakeLine(line));
    return out;
}

static std::wstring ReadTextFile(const std::wstring& path) {
    std::ifstream in(path.c_str(), std::ios::binary);
    if (!in) return {};
    std::string bytes((std::istreambuf_iterator<char>(in)), {});
    if (bytes.size() >= 3 && (uint8_t)bytes[0] == 0xEF && (uint8_t)bytes[1] == 0xBB && (uint8_t)bytes[2] == 0xBF) {
        return Utf8ToWide(bytes.substr(3));
    }
    if (bytes.size() >= 2 && (uint8_t)bytes[0] == 0xFF && (uint8_t)bytes[1] == 0xFE) {
        std::wstring out;
        for (size_t i = 2; i + 1 < bytes.size(); i += 2) {
            out.push_back(static_cast<wchar_t>((uint8_t)bytes[i] | ((uint8_t)bytes[i + 1] << 8)));
        }
        return out;
    }
    auto utf8 = Utf8ToWide(bytes);
    return utf8.empty() && !bytes.empty() ? AcpToWide(bytes) : utf8;
}

static std::wstring Trim(std::wstring text) {
    while (!text.empty() && iswspace(text.front())) text.erase(text.begin());
    while (!text.empty() && iswspace(text.back())) text.pop_back();
    return text;
}

static void AppendUtf8CodePoint(std::string& out, uint32_t cp) {
    if (cp <= 0x7f) {
        out.push_back(static_cast<char>(cp));
    } else if (cp <= 0x7ff) {
        out.push_back(static_cast<char>(0xc0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    } else if (cp <= 0xffff) {
        out.push_back(static_cast<char>(0xe0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    } else {
        out.push_back(static_cast<char>(0xf0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
    }
}

static int HexNibble(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

static bool ParseHex4(const std::string& text, size_t pos, uint32_t& value) {
    if (pos + 4 > text.size()) return false;
    value = 0;
    for (size_t i = 0; i < 4; ++i) {
        int nibble = HexNibble(text[pos + i]);
        if (nibble < 0) return false;
        value = (value << 4) | static_cast<uint32_t>(nibble);
    }
    return true;
}

static bool ParseJsonStringAt(const std::string& json, size_t quotePos, std::wstring& value) {
    if (quotePos >= json.size() || json[quotePos] != '"') return false;
    std::string utf8;
    for (size_t i = quotePos + 1; i < json.size(); ++i) {
        unsigned char ch = static_cast<unsigned char>(json[i]);
        if (ch == '"') {
            value = Utf8ToWide(utf8);
            return true;
        }
        if (ch != '\\') {
            utf8.push_back(static_cast<char>(ch));
            continue;
        }
        if (++i >= json.size()) return false;
        char esc = json[i];
        switch (esc) {
        case '"': utf8.push_back('"'); break;
        case '\\': utf8.push_back('\\'); break;
        case '/': utf8.push_back('/'); break;
        case 'b': utf8.push_back('\b'); break;
        case 'f': utf8.push_back('\f'); break;
        case 'n': utf8.push_back('\n'); break;
        case 'r': utf8.push_back('\r'); break;
        case 't': utf8.push_back('\t'); break;
        case 'u': {
            uint32_t cp = 0;
            if (!ParseHex4(json, i + 1, cp)) return false;
            i += 4;
            if (cp >= 0xd800 && cp <= 0xdbff && i + 6 < json.size() && json[i + 1] == '\\' && json[i + 2] == 'u') {
                uint32_t low = 0;
                if (ParseHex4(json, i + 3, low) && low >= 0xdc00 && low <= 0xdfff) {
                    cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00);
                    i += 6;
                }
            }
            AppendUtf8CodePoint(utf8, cp);
            break;
        }
        default:
            utf8.push_back(esc);
            break;
        }
    }
    return false;
}

static bool ExtractJsonStringValue(const std::string& json, const std::string& key, size_t start, std::wstring& value) {
    size_t keyPos = json.find(key, start);
    if (keyPos == std::string::npos) return false;
    size_t colon = json.find(':', keyPos + key.size());
    if (colon == std::string::npos) return false;
    size_t quote = json.find('"', colon + 1);
    if (quote == std::string::npos) return false;
    return ParseJsonStringAt(json, quote, value);
}

static bool ExtractJsonScalarValue(const std::string& json, const std::string& key, size_t start, std::wstring& value) {
    size_t keyPos = json.find(key, start);
    if (keyPos == std::string::npos) return false;
    size_t colon = json.find(':', keyPos + key.size());
    if (colon == std::string::npos) return false;
    size_t pos = colon + 1;
    while (pos < json.size() && isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    if (pos >= json.size()) return false;
    if (json[pos] == '"') return ParseJsonStringAt(json, pos, value);
    size_t end = pos;
    while (end < json.size() && json[end] != ',' && json[end] != '}' && !isspace(static_cast<unsigned char>(json[end]))) ++end;
    if (end <= pos) return false;
    value = Utf8ToWide(json.substr(pos, end - pos));
    return !value.empty();
}

static std::wstring StripCqCodes(std::wstring text) {
    for (size_t pos = text.find(L"[CQ:"); pos != std::wstring::npos; pos = text.find(L"[CQ:", pos)) {
        size_t end = text.find(L']', pos);
        if (end == std::wstring::npos) break;
        text.replace(pos, end - pos + 1, L"");
    }
    return Trim(text);
}

struct NapcatEvent {
    std::wstring text;
    std::wstring raw;
    std::wstring userId;
    std::wstring groupId;
    std::wstring nickname;
    std::wstring messageType;
};

static std::wstring ExceptionMessageToWide(const std::exception& ex);

static std::wstring ExtractDeepSeekContent(const std::string& json) {
    std::wstring value;
    size_t choices = json.find("\"choices\"");
    size_t message = choices == std::string::npos ? std::string::npos : json.find("\"message\"", choices);
    if (message != std::string::npos && ExtractJsonStringValue(json, "\"content\"", message, value)) return value;
    if (ExtractJsonStringValue(json, "\"message\"", 0, value)) throw std::runtime_error(WideToUtf8(value));
    throw std::runtime_error("DeepSeek response parse failed");
}

static std::string JsonEscapeUtf8(const std::wstring& text) {
    std::string utf8 = WideToUtf8(text);
    std::string out;
    out.reserve(utf8.size() + 32);
    for (unsigned char ch : utf8) {
        switch (ch) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (ch < 0x20) {
                static const char* hex = "0123456789abcdef";
                out += "\\u00";
                out.push_back(hex[ch >> 4]);
                out.push_back(hex[ch & 0x0f]);
            } else {
                out.push_back(static_cast<char>(ch));
            }
            break;
        }
    }
    return out;
}

static void WriteUtf8BomFile(const std::wstring& path, const std::wstring& text) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw std::runtime_error("create generated txt failed");
    DWORD written = 0;
    const unsigned char bom[] = { 0xef, 0xbb, 0xbf };
    WriteFile(file, bom, 3, &written, nullptr);
    std::string utf8 = WideToUtf8(text);
    if (!utf8.empty()) WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
    CloseHandle(file);
}
