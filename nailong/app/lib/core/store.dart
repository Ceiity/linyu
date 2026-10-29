import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../ui/theme.dart';
import 'ssh.dart';

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

/// 进行中的部署：用于 App 被系统回收后重新打开时自动接上进度。
/// 连接信息（含 SSH 密码/私钥）只在部署期间用 Android Keystore 加密暂存，部署结束立即删除，超过 12 小时自动作废。
class PendingDeploy {
  final SshTarget target;
  final bool savePassword;
  final int startedAt;

  PendingDeploy(this.target, this.savePassword, this.startedAt);
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
  int seedColor = brandGraphite;
  ButtonLook buttonLook = ButtonLook.light;
  SourceSettings sources = SourceSettings();
  bool onboarded = false;
  PendingDeploy? pending;

  ServerProfile? get current => servers.where((s) => s.id == currentId).firstOrNull;

  Future<void> load() async {
    _prefs = await SharedPreferences.getInstance();
    themeMode = ThemeMode.values[(_prefs.getInt('themeMode') ?? ThemeMode.light.index).clamp(0, 2)];
    dynamicColor = _prefs.getBool('dynamicColor') ?? false;
    seedColor = _prefs.getInt('seedColor') ?? brandGraphite;
    if (seedColor == 0xFFFFC83D) seedColor = brandGraphite; // 旧版默认的黄色，迁移到石墨灰
    buttonLook = ButtonLook.values[(_prefs.getInt('buttonLook') ?? 0).clamp(0, 1)];
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
    await _loadPending();
    currentId = _prefs.getString('currentServer');
    if (current == null && servers.isNotEmpty) currentId = servers.first.id;
  }

  static const _pendingTtl = Duration(hours: 12);

  Future<void> _loadPending() async {
    try {
      final raw = _prefs.getString('pendingDeploy');
      if (raw == null) return;
      final j = Map<String, dynamic>.from(jsonDecode(raw) as Map);
      final at = j['at'] as int;
      if (DateTime.now().millisecondsSinceEpoch - at > _pendingTtl.inMilliseconds) {
        await finishPending();
        return;
      }
      pending = PendingDeploy(
        SshTarget(
          host: j['host'] as String,
          port: j['port'] as int,
          user: j['user'] as String,
          password: await secure.read(key: 'pend:pw'),
          privateKeyPem: await secure.read(key: 'pend:key'),
          passphrase: await secure.read(key: 'pend:pass'),
        ),
        j['savePassword'] == true,
        at,
      );
    } catch (_) {
      pending = null;
    }
  }

  /// 部署开始时调用（静默写入，不触发界面重建）。
  Future<void> setPending(SshTarget t, {required bool savePassword}) async {
    final at = DateTime.now().millisecondsSinceEpoch;
    await _prefs.setString(
      'pendingDeploy',
      jsonEncode({'host': t.host, 'port': t.port, 'user': t.user, 'savePassword': savePassword, 'at': at}),
    );
    await secure.write(key: 'pend:pw', value: t.password ?? '');
    await secure.write(key: 'pend:key', value: t.privateKeyPem ?? '');
    await secure.write(key: 'pend:pass', value: t.passphrase ?? '');
    pending = PendingDeploy(t, savePassword, at);
  }

  /// 删除落盘的连接信息（部署结束/放弃时调用）；内存里的 [pending] 保持不变，避免界面突然切换。
  Future<void> finishPending() async {
    await _prefs.remove('pendingDeploy');
    for (final k in ['pend:pw', 'pend:key', 'pend:pass']) {
      await secure.delete(key: k);
    }
  }

  /// 彻底清除并刷新界面（用户离开部署页 / 点了“进入首页”）。
  Future<void> clearPending() async {
    await finishPending();
    if (pending != null) {
      pending = null;
      notifyListeners();
    }
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

  void setButtonLook(ButtonLook v) {
    buttonLook = v;
    _prefs.setInt('buttonLook', v.index);
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
