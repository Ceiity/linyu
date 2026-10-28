import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'login_crypto.dart';

class ApiException implements Exception {
  final String message;
  final String code;
  final int status;

  ApiException(this.message, {this.code = '', this.status = 0});

  bool get unauthorized => status == 401 || code == 'UNAUTHORIZED';

  @override
  String toString() => message;
}

/// 面板 HTTP API 客户端。会话 Token 通过 Cookie 发送，与浏览器一致。
class ApiClient {
  final String baseUrl;
  String? token;
  final http.Client _http = http.Client();

  /// 会话失效时回调（例如被改密码踢下线）。
  void Function()? onUnauthorized;

  ApiClient(this.baseUrl, {this.token});

  Uri _uri(String path, [Map<String, String>? query]) {
    final u = Uri.parse('$baseUrl$path');
    return query == null ? u : u.replace(queryParameters: query);
  }

  Map<String, String> _headers({bool json = false}) => {
    'Accept': 'application/json',
    if (json) 'Content-Type': 'application/json',
    if (token != null && token!.isNotEmpty) 'Cookie': 'adb_session=$token',
    'User-Agent': 'LinyuApp/1.0 (Flutter)',
  };

  Future<dynamic> get(String path, {Map<String, String>? query, Duration timeout = const Duration(seconds: 20)}) async {
    final res = await _send(() => _http.get(_uri(path, query), headers: _headers()), timeout);
    return _decode(res);
  }

  Future<dynamic> post(
    String path, [
    Map<String, dynamic>? body,
    Duration timeout = const Duration(seconds: 60),
  ]) async {
    final res = await _send(
      () => _http.post(_uri(path), headers: _headers(json: true), body: jsonEncode(body ?? {})),
      timeout,
    );
    return _decode(res);
  }

  Future<http.Response> _send(Future<http.Response> Function() fn, Duration timeout) async {
    try {
      return await fn().timeout(timeout);
    } on TimeoutException {
      throw ApiException('连接服务器超时');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException('无法连接服务器：${_short(e)}');
    }
  }

  dynamic _decode(http.Response res) {
    Map<String, dynamic> j = {};
    try {
      final v = jsonDecode(utf8.decode(res.bodyBytes));
      if (v is Map<String, dynamic>) j = v;
    } catch (_) {}
    if (res.statusCode == 401) {
      onUnauthorized?.call();
      throw ApiException(j['message']?.toString() ?? '未登录或登录已失效', code: 'UNAUTHORIZED', status: 401);
    }
    if (res.statusCode >= 400 || j['ok'] != true) {
      throw ApiException(
        (j['message']?.toString().isNotEmpty ?? false) ? j['message'].toString() : '操作失败（HTTP ${res.statusCode}）',
        code: j['code']?.toString() ?? '',
        status: res.statusCode,
      );
    }
    return j['data'];
  }

  /// 加密登录，成功返回会话 Token。
  Future<String> login(String username, String password) async {
    final ch = await get('/api/login/challenge');
    if (ch is! Map || ch['enabled'] != true) {
      throw ApiException('服务器未启用加密登录，请升级面板');
    }
    final body = buildEncryptedLogin(challenge: Map<String, dynamic>.from(ch), username: username, password: password);
    final res = await _send(
      () => _http.post(_uri('/api/login'), headers: _headers(json: true), body: jsonEncode(body)),
      const Duration(seconds: 20),
    );
    Map<String, dynamic> j = {};
    try {
      j = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {}
    if (res.statusCode != 200 || j['ok'] != true) {
      throw ApiException(j['message']?.toString() ?? '登录失败', code: j['code']?.toString() ?? '', status: res.statusCode);
    }
    final cookie = res.headers['set-cookie'] ?? '';
    final m = RegExp(r'adb_session=([^;,\s]+)').firstMatch(cookie);
    if (m == null) throw ApiException('服务器未返回会话');
    token = m.group(1);
    return token!;
  }

  void close() => _http.close();

  static String _short(Object e) {
    final s = e.toString();
    if (s.contains('Connection refused')) return '连接被拒绝';
    if (s.contains('No route to host')) return '主机不可达';
    if (s.contains('Failed host lookup')) return '域名解析失败';
    if (s.contains('HandshakeException') || s.contains('CERTIFICATE')) return 'HTTPS 证书错误';
    return s.length > 80 ? '${s.substring(0, 80)}…' : s;
  }
}

class DiscoveryResult {
  final String baseUrl;
  final String version;

  DiscoveryResult(this.baseUrl, this.version);
}

/// 根据用户输入的 IP / 域名自动寻找面板。
/// 只填 IP 时优先 7070，再顺延 7071-7079（安装脚本会自动顺延空闲端口）。
Future<DiscoveryResult?> discoverPanel(String input) async {
  final candidates = panelCandidates(input);
  if (candidates.isEmpty) return null;
  final client = http.Client();
  try {
    final futures = candidates.map((base) => _probe(client, base)).toList();
    for (final f in futures) {
      final r = await f;
      if (r != null) return r;
    }
    return null;
  } finally {
    client.close();
  }
}

List<String> panelCandidates(String input) {
  var raw = input.trim();
  if (raw.isEmpty) return [];
  raw = raw.replaceAll(RegExp(r'/+$'), '');
  final hasScheme = raw.startsWith('http://') || raw.startsWith('https://');
  final uri = Uri.tryParse(hasScheme ? raw : 'http://$raw');
  if (uri == null || uri.host.isEmpty) return [];
  final host = uri.host.contains(':') ? '[${uri.host}]' : uri.host;
  final explicitPort = RegExp(r'^(https?://)?(\[[^\]]+\]|[^/:]+):\d+').hasMatch(raw);
  final path = uri.path == '/' ? '' : uri.path;
  final out = <String>[];
  if (explicitPort) {
    out.add('${uri.scheme}://$host:${uri.port}$path');
    if (!hasScheme) out.add('https://$host:${uri.port}$path');
  } else if (hasScheme) {
    out.add('${uri.scheme}://$host$path');
    out.add('${uri.scheme}://$host:7070$path');
  } else {
    for (var p = 7070; p < 7080; p++) {
      out.add('http://$host:$p');
    }
    final isIp = RegExp(r'^[\d.]+$').hasMatch(uri.host) || uri.host.contains(':');
    if (!isIp) {
      out.add('https://$host');
      out.add('http://$host');
    }
  }
  return out.toSet().toList();
}

Future<DiscoveryResult?> _probe(http.Client client, String base) async {
  try {
    final res = await client
        .get(Uri.parse('$base/api/health'), headers: {'Accept': 'application/json'})
        .timeout(const Duration(seconds: 5));
    if (res.statusCode != 200) return null;
    final j = jsonDecode(utf8.decode(res.bodyBytes));
    if (j is Map && j['ok'] == true && (j['data'] is Map) && j['data']['status'] == 'ok') {
      final server = res.headers['server'] ?? '';
      final v = RegExp(r'AstrBotPanel/([\w.\-]+)').firstMatch(server)?.group(1) ?? j['version']?.toString() ?? '';
      return DiscoveryResult(base, v);
    }
  } catch (_) {}
  return null;
}
