import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 服务器档案（不含任何密钥，存 SharedPreferences）。
class ServerProfile {
  final String id;
  String name;
  String host;
  int port;
  String user;
  String hostKey;
  int agentPort;
  String deviceId;
  int lastOnline;
  int createdAt;

  ServerProfile({
    required this.id,
    required this.name,
    required this.host,
    required this.port,
    required this.user,
    required this.hostKey,
    required this.agentPort,
    required this.deviceId,
    this.lastOnline = 0,
    int? createdAt,
  }) : createdAt = createdAt ?? DateTime.now().millisecondsSinceEpoch;

  String get address => port == 22 ? host : '$host:$port';

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'host': host,
    'port': port,
    'user': user,
    'hostKey': hostKey,
    'agentPort': agentPort,
    'deviceId': deviceId,
    'lastOnline': lastOnline,
    'createdAt': createdAt,
  };

  factory ServerProfile.fromJson(Map<String, dynamic> j) => ServerProfile(
    id: j['id'] as String,
    name: j['name'] as String? ?? '',
    host: j['host'] as String,
    port: j['port'] as int? ?? 22,
    user: j['user'] as String? ?? 'root',
    hostKey: j['hostKey'] as String? ?? '',
    agentPort: j['agentPort'] as int? ?? 0,
    deviceId: j['deviceId'] as String? ?? '',
    lastOnline: j['lastOnline'] as int? ?? 0,
    createdAt: j['createdAt'] as int?,
  );
}

/// 用户配置的下载源（只含 HTTPS 地址，不硬编码任何第三方镜像）。
class SourceSettings {
  List<Map<String, dynamic>> github;
  List<String> registries;
  List<String> pypi;
  List<String> dockerApt;

  SourceSettings({this.github = const [], this.registries = const [], this.pypi = const [], this.dockerApt = const []});

  Map<String, dynamic> toJson() => {'github': github, 'registries': registries, 'pypi': pypi, 'docker_apt': dockerApt};

  factory SourceSettings.fromJson(Map<String, dynamic> j) => SourceSettings(
    github: ((j['github'] ?? []) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList(),
    registries: ((j['registries'] ?? []) as List).map((e) => e.toString()).toList(),
    pypi: ((j['pypi'] ?? []) as List).map((e) => e.toString()).toList(),
    dockerApt: ((j['docker_apt'] ?? []) as List).map((e) => e.toString()).toList(),
  );

  /// 传给安装器：官方源始终作为兜底。
  Map<String, dynamic> forInstaller() => {
    'docker_apt': [...dockerApt, 'https://download.docker.com'],
    'registries': registries,
    'pypi': [...pypi, 'https://pypi.org/simple'],
    'github': github,
  };
}

String newId([int n = 16]) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  final r = Random.secure();
  return List.generate(n, (_) => chars[r.nextInt(chars.length)]).join();
}

/// 全局状态：服务器列表、当前服务器、主题、下载源。
/// 私钥、访问令牌、（经用户同意保存的）SSH 密码只存 Android Keystore 保护的安全存储。
class AppStore extends ChangeNotifier {
  static const secure = FlutterSecureStorage(aOptions: AndroidOptions(resetOnError: false));
  late SharedPreferences _prefs;

  List<ServerProfile> servers = [];
  String? currentId;
  ThemeMode themeMode = ThemeMode.light;
  bool dynamicColor = false;
  int seedColor = 0xFFFFC83D;
  SourceSettings sources = SourceSettings();
  bool onboarded = false;

  ServerProfile? get current => servers.where((s) => s.id == currentId).firstOrNull;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    themeMode = ThemeMode.values[(_prefs.getInt('themeMode') ?? ThemeMode.light.index).clamp(0, 2)];
    dynamicColor = _prefs.getBool('dynamicColor') ?? false;
    seedColor = _prefs.getInt('seedColor') ?? 0xFFFFC83D;
    onboarded = _prefs.getBool('onboarded') ?? false;
    try {
      servers = ((jsonDecode(_prefs.getString('servers') ?? '[]')) as List)
          .map((e) => ServerProfile.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    } catch (_) {
      servers = [];
    }
    try {
      sources = SourceSettings.fromJson(
        Map<String, dynamic>.from(jsonDecode(_prefs.getString('sources') ?? '{}') as Map),
      );
    } catch (_) {}
    currentId = _prefs.getString('currentServer');
    if (current == null && servers.isNotEmpty) currentId = servers.first.id;
  }

  Future<void> _saveServers() async {
    await _prefs.setString('servers', jsonEncode(servers.map((e) => e.toJson()).toList()));
  }

  Future<void> upsertServer(ServerProfile p) async {
    servers.removeWhere((s) => s.id == p.id);
    servers.insert(0, p);
    currentId = p.id;
    await _prefs.setString('currentServer', p.id);
    await _saveServers();
    notifyListeners();
  }

  Future<void> select(String id) async {
    currentId = id;
    await _prefs.setString('currentServer', id);
    notifyListeners();
  }

  Future<void> touchOnline(ServerProfile p) async {
    p.lastOnline = DateTime.now().millisecondsSinceEpoch;
    await _saveServers();
  }

  Future<void> rename(ServerProfile p, String name) async {
    p.name = name.trim().isEmpty ? p.host : name.trim();
    await _saveServers();
    notifyListeners();
  }

  Future<void> removeServer(ServerProfile p) async {
    servers.removeWhere((s) => s.id == p.id);
    for (final k in ['key', 'token', 'tokexp', 'pw']) {
      await secure.delete(key: '$k:${p.id}');
    }
    if (currentId == p.id) {
      currentId = servers.isEmpty ? null : servers.first.id;
      if (currentId == null) {
        await _prefs.remove('currentServer');
      } else {
        await _prefs.setString('currentServer', currentId!);
      }
    }
    await _saveServers();
    notifyListeners();
  }

  // ---- 安全存储
  Future<String?> secret(String kind, String id) => secure.read(key: '$kind:$id');

  Future<void> setSecret(String kind, String id, String? value) =>
      value == null ? secure.delete(key: '$kind:$id') : secure.write(key: '$kind:$id', value: value);

  // ---- 已信任的主机指纹（首次连接时用户确认）
  String? knownHost(String hostPort) => _prefs.getString('hostkey:$hostPort');

  Future<void> trustHost(String hostPort, String fingerprint) => _prefs.setString('hostkey:$hostPort', fingerprint);

  Future<void> forgetHost(String hostPort) => _prefs.remove('hostkey:$hostPort');

  // ---- 设置
  void setThemeMode(ThemeMode m) {
    themeMode = m;
    _prefs.setInt('themeMode', m.index);
    notifyListeners();
  }

  void setDynamicColor(bool v) {
    dynamicColor = v;
    _prefs.setBool('dynamicColor', v);
    notifyListeners();
  }

  void setSeedColor(int c) {
    seedColor = c;
    dynamicColor = false;
    _prefs.setInt('seedColor', c);
    _prefs.setBool('dynamicColor', false);
    notifyListeners();
  }

  Future<void> setSources(SourceSettings s) async {
    sources = s;
    await _prefs.setString('sources', jsonEncode(s.toJson()));
    notifyListeners();
  }

  Future<void> setOnboarded() async {
    onboarded = true;
    await _prefs.setBool('onboarded', true);
  }
}

class StoreScope extends InheritedNotifier<AppStore> {
  const StoreScope({super.key, required AppStore store, required super.child}) : super(notifier: store);

  static AppStore of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<StoreScope>()!.notifier!;

  static AppStore read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<StoreScope>()!.widget as StoreScope).notifier!;
}
