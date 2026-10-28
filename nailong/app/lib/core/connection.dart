import 'dart:async';
import 'dart:math';

import 'package:material_ui/material_ui.dart';

import 'agent_api.dart';
import 'errors.dart';
import 'ssh.dart';
import 'store.dart';

enum ConnState { idle, connecting, online, reconnecting, offline, unauthorized }

/// 当前服务器的长连接：用 App 专属密钥建立 SSH（服务器侧只允许转发到 Agent 端口）→
/// 本地隧道 → Agent API。断线后指数退避自动重连。
class ServerConnection extends ChangeNotifier with WidgetsBindingObserver {
  final AppStore store;
  final ServerProfile profile;

  ServerConnection(this.store, this.profile) {
    WidgetsBinding.instance.addObserver(this);
  }

  ConnState state = ConnState.idle;
  String? error;
  AgentApi? api;
  SshSession? _ssh;
  LocalTunnel? _tunnel;
  int _attempt = 0;
  Timer? _retry;
  bool _disposed = false;
  bool _paused = false;

  bool get online => state == ConnState.online && api != null;

  void _set(ConnState s, [String? err]) {
    state = s;
    error = err;
    if (!_disposed) notifyListeners();
  }

  Future<void> connect() async {
    if (_disposed || state == ConnState.connecting) return;
    _retry?.cancel();
    _set(_attempt == 0 ? ConnState.connecting : ConnState.reconnecting, error);
    try {
      final key = await store.secret('key', profile.id);
      final token = await store.secret('token', profile.id);
      if (key == null || token == null) {
        _set(ConnState.unauthorized, '本机没有该服务器的授权，请重新配对');
        return;
      }
      await _teardown();
      final ssh = await SshSession.connect(
        SshTarget(host: profile.host, port: profile.port, user: profile.user, privateKeyPem: key),
        knownFingerprint: profile.hostKey,
        decide: (type, fp, known) => false,
        retries: 0,
        probePrivileges: false,
      );
      final tunnel = LocalTunnel(ssh, profile.agentPort);
      await tunnel.open();
      final api = AgentApi(tunnel.localPort, token: token);
      api.onUnauthorized = () => _set(ConnState.unauthorized, '授权已失效或被撤销，请重新配对');
      await api.get('/api/me', timeout: const Duration(seconds: 15));
      _ssh = ssh;
      _tunnel = tunnel;
      this.api = api;
      _attempt = 0;
      store.touchOnline(profile);
      _set(ConnState.online);
      ssh.done.whenComplete(_onDropped).ignore();
      unawaited(_maybeRotate());
    } on AgentException catch (e) {
      if (e.unauthorized) {
        _set(ConnState.unauthorized, e.message);
      } else {
        _scheduleRetry(e.message);
      }
    } on NailongError catch (e) {
      if (e.code == 'HOSTKEY_CHANGED' || e.code == 'AUTH_FAILED') {
        _set(ConnState.unauthorized, e.code == 'AUTH_FAILED' ? '服务器拒绝了本机密钥，请重新配对' : e.message);
      } else {
        _scheduleRetry(e.message);
      }
    } catch (e) {
      _scheduleRetry(e.toString());
    }
  }

  void _onDropped() {
    if (_disposed || state == ConnState.unauthorized) return;
    api = null;
    _scheduleRetry('连接已断开');
  }

  void _scheduleRetry(String msg) {
    if (_disposed) return;
    _set(ConnState.reconnecting, msg);
    if (_paused) return;
    final delay = Duration(seconds: min(30, 1 << min(_attempt, 5)));
    _attempt++;
    _retry?.cancel();
    _retry = Timer(delay, connect);
  }

  /// 令牌剩余不足 7 天时自动轮换。
  Future<void> _maybeRotate() async {
    final exp = int.tryParse(await store.secret('tokexp', profile.id) ?? '') ?? 0;
    if (exp - DateTime.now().millisecondsSinceEpoch ~/ 1000 > 7 * 86400) return;
    try {
      final r = Map<String, dynamic>.from(await api!.post('/api/token/rotate') as Map);
      await store.setSecret('token', profile.id, r['token'] as String);
      await store.setSecret('tokexp', profile.id, '${r['expires_at']}');
      api!.token = r['token'] as String;
    } catch (_) {}
  }

  Future<void> rotateNow() async {
    final r = Map<String, dynamic>.from(await api!.post('/api/token/rotate') as Map);
    await store.setSecret('token', profile.id, r['token'] as String);
    await store.setSecret('tokexp', profile.id, '${r['expires_at']}');
    api!.token = r['token'] as String;
  }

  Future<void> _teardown() async {
    api?.close();
    api = null;
    await _tunnel?.close();
    _tunnel = null;
    _ssh?.close();
    _ssh = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final s = state;
    if (s == AppLifecycleState.paused || s == AppLifecycleState.hidden) {
      _paused = true;
    } else if (s == AppLifecycleState.resumed) {
      _paused = false;
      if (this.state == ConnState.reconnecting || (this.state == ConnState.online && (_ssh?.isClosed ?? true))) {
        _attempt = 0;
        connect();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    WidgetsBinding.instance.removeObserver(this);
    _retry?.cancel();
    _teardown();
    super.dispose();
  }
}
