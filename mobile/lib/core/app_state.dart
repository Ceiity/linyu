import 'dart:convert';

import 'package:material_ui/material_ui.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

class ServerEntry {
  final String baseUrl;
  String name;
  String version;
  int lastUsed;

  ServerEntry({required this.baseUrl, required this.name, this.version = '', this.lastUsed = 0});

  String get host => Uri.tryParse(baseUrl)?.authority ?? baseUrl;

  Map<String, dynamic> toJson() => {'baseUrl': baseUrl, 'name': name, 'version': version, 'lastUsed': lastUsed};

  factory ServerEntry.fromJson(Map<String, dynamic> j) => ServerEntry(
    baseUrl: j['baseUrl'] as String,
    name: (j['name'] ?? '') as String,
    version: (j['version'] ?? '') as String,
    lastUsed: (j['lastUsed'] ?? 0) as int,
  );
}

const presetColors = <int>[
  0xFF007AFF,
  0xFF5856D6,
  0xFFCB30E0,
  0xFFFF2D55,
  0xFFFF8D28,
  0xFFFFCC00,
  0xFF34C759,
  0xFF00C7BE,
  0xFF8E8E93,
];

class AppState extends ChangeNotifier {
  static const _secure = FlutterSecureStorage();
  late SharedPreferences _prefs;

  List<ServerEntry> servers = [];
  ServerEntry? current;
  ApiClient? api;

  ThemeMode themeMode = ThemeMode.system;
  int seedColor = presetColors.first;
  bool dynamicColor = false;
  bool pureBlack = false;

  bool get loggedIn => api?.token != null;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    themeMode = ThemeMode.values[(_prefs.getInt('themeMode') ?? 0).clamp(0, 2)];
    seedColor = _prefs.getInt('seedColor') ?? presetColors.first;
    dynamicColor = _prefs.getBool('dynamicColor') ?? false;
    pureBlack = _prefs.getBool('pureBlack') ?? false;
    try {
      final raw = jsonDecode(_prefs.getString('servers') ?? '[]') as List;
      servers = raw.map((e) => ServerEntry.fromJson(Map<String, dynamic>.from(e))).toList();
    } catch (_) {
      servers = [];
    }
    final cur = _prefs.getString('currentServer');
    if (cur != null) {
      for (final s in servers) {
        if (s.baseUrl == cur) {
          current = s;
          String? token;
          try {
            token = await _secure.read(key: _tokenKey(s.baseUrl));
          } catch (_) {}
          _openApi(s, token);
        }
      }
    }
  }

  String _tokenKey(String base) => 'session::$base';

  void _openApi(ServerEntry s, String? token) {
    api?.close();
    api = ApiClient(s.baseUrl, token: token)..onUnauthorized = _handleUnauthorized;
  }

  void _handleUnauthorized() {
    if (api?.token == null) return;
    api!.token = null;
    if (current != null) _secure.delete(key: _tokenKey(current!.baseUrl));
    notifyListeners();
  }

  Future<void> _saveServers() async {
    servers.sort((a, b) => b.lastUsed.compareTo(a.lastUsed));
    await _prefs.setString('servers', jsonEncode(servers.map((e) => e.toJson()).toList()));
  }

  /// 选中服务器（新增或切换），已保存会话则直接进入。
  Future<void> useServer(String baseUrl, {String version = '', String? name}) async {
    var s = servers.where((e) => e.baseUrl == baseUrl).firstOrNull;
    if (s == null) {
      s = ServerEntry(baseUrl: baseUrl, name: name ?? Uri.parse(baseUrl).host, version: version);
      servers.add(s);
    } else if (version.isNotEmpty) {
      s.version = version;
    }
    s.lastUsed = DateTime.now().millisecondsSinceEpoch;
    current = s;
    String? token;
    try {
      token = await _secure.read(key: _tokenKey(baseUrl));
    } catch (_) {}
    _openApi(s, token);
    await _prefs.setString('currentServer', baseUrl);
    await _saveServers();
    notifyListeners();
  }

  Future<void> removeServer(ServerEntry s) async {
    servers.remove(s);
    await _secure.delete(key: _tokenKey(s.baseUrl));
    if (current == s) {
      current = null;
      api?.close();
      api = null;
      await _prefs.remove('currentServer');
    }
    await _saveServers();
    notifyListeners();
  }

  Future<void> renameServer(ServerEntry s, String name) async {
    s.name = name.trim().isEmpty ? s.host : name.trim();
    await _saveServers();
    notifyListeners();
  }

  Future<void> login(String username, String password) async {
    final a = api!;
    final token = await a.login(username, password);
    await _secure.write(key: _tokenKey(a.baseUrl), value: token);
    notifyListeners();
  }

  Future<void> logout() async {
    if (current != null) await _secure.delete(key: _tokenKey(current!.baseUrl));
    api?.token = null;
    notifyListeners();
  }

  /// 回到服务器选择页（不清除会话）。
  Future<void> leaveServer() async {
    current = null;
    api?.close();
    api = null;
    await _prefs.remove('currentServer');
    notifyListeners();
  }

  void setThemeMode(ThemeMode m) {
    themeMode = m;
    _prefs.setInt('themeMode', m.index);
    notifyListeners();
  }

  void setSeedColor(int c) {
    seedColor = c;
    dynamicColor = false;
    _prefs.setInt('seedColor', c);
    _prefs.setBool('dynamicColor', false);
    notifyListeners();
  }

  void setDynamicColor(bool v) {
    dynamicColor = v;
    _prefs.setBool('dynamicColor', v);
    notifyListeners();
  }

  void setPureBlack(bool v) {
    pureBlack = v;
    _prefs.setBool('pureBlack', v);
    notifyListeners();
  }
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  static AppState read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<AppScope>()!.widget as AppScope).notifier!;
}
