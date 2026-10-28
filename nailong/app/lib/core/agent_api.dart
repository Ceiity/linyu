import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/io.dart';

class AgentException implements Exception {
  final String message;
  final int status;
  final String code;

  AgentException(this.message, {this.status = 0, this.code = ''});

  bool get unauthorized => status == 401;

  @override
  String toString() => message;
}

/// 通过 SSH 隧道访问 Agent（http://127.0.0.1:<本地隧道端口>）。
class AgentApi {
  final int localPort;
  String? token;
  final http.Client _http = http.Client();
  void Function()? onUnauthorized;

  AgentApi(this.localPort, {this.token});

  String get base => 'http://127.0.0.1:$localPort';

  Map<String, String> get _headers => {
    'Accept': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Future<dynamic> get(String path, {Map<String, String>? query, Duration timeout = const Duration(seconds: 30)}) =>
      _send('GET', path, query: query, timeout: timeout);

  Future<dynamic> post(String path, [Object? body, Duration timeout = const Duration(seconds: 60)]) =>
      _send('POST', path, body: body, timeout: timeout);

  Future<dynamic> put(String path, Object? body) => _send('PUT', path, body: body);

  Future<dynamic> delete(String path) => _send('DELETE', path);

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
    Duration timeout = const Duration(seconds: 30),
  }) async {
    var uri = Uri.parse('$base$path');
    if (query != null) uri = uri.replace(queryParameters: query);
    final req = http.Request(method, uri)..headers.addAll(_headers);
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    http.Response res;
    try {
      res = await http.Response.fromStream(await _http.send(req).timeout(timeout));
    } on TimeoutException {
      throw AgentException('请求超时，服务器响应较慢');
    } on SocketException {
      throw AgentException('与服务器的安全连接已断开，正在重连');
    } on http.ClientException {
      throw AgentException('与服务器的安全连接已断开，正在重连');
    }
    return _decode(res);
  }

  dynamic _decode(http.Response res) {
    Map<String, dynamic> j = {};
    try {
      final v = jsonDecode(utf8.decode(res.bodyBytes));
      if (v is Map<String, dynamic>) j = v;
    } catch (_) {}
    if (res.statusCode == 401) {
      onUnauthorized?.call();
      throw AgentException(j['message']?.toString() ?? '授权已失效，请重新配对', status: 401, code: 'AUTH');
    }
    if (res.statusCode >= 400 || j['ok'] != true) {
      final detail = j['detail'];
      final msg = j['message'] ?? (detail is String ? detail : null) ?? '操作失败（HTTP ${res.statusCode}）';
      throw AgentException(msg.toString(), status: res.statusCode, code: j['code']?.toString() ?? '');
    }
    return j['data'];
  }

  /// 上传文件（插件 ZIP / 备份）。
  Future<dynamic> upload(String path, String filename, Stream<List<int>> data, int length) async {
    final req = http.MultipartRequest('POST', Uri.parse('$base$path'))..headers.addAll(_headers);
    req.files.add(http.MultipartFile('file', data, length, filename: filename));
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(minutes: 10)));
    return _decode(res);
  }

  Future<Uint8List> download(String path) async {
    final res = await _http.get(Uri.parse('$base$path'), headers: _headers).timeout(const Duration(minutes: 10));
    if (res.statusCode != 200) {
      throw AgentException('下载失败（HTTP ${res.statusCode}）', status: res.statusCode);
    }
    return res.bodyBytes;
  }

  /// 轮询后台任务直到结束。
  Stream<Map<String, dynamic>> watchTask(String id) async* {
    while (true) {
      final t = Map<String, dynamic>.from(await get('/api/tasks/$id') as Map);
      yield t;
      if (t['status'] != 'running') return;
      await Future.delayed(const Duration(milliseconds: 1200));
    }
  }

  /// 实时日志：首帧发送令牌（不放在 URL，避免出现在任何访问日志里）。
  Stream<Map<String, dynamic>> logStream(String target, {int tail = 300}) {
    final ch = IOWebSocketChannel.connect(
      Uri.parse('ws://127.0.0.1:$localPort/ws/logs'),
      pingInterval: const Duration(seconds: 20),
    );
    ch.sink.add(jsonEncode({'token': token, 'target': target, 'tail': tail}));
    late StreamController<Map<String, dynamic>> ctrl;
    ctrl = StreamController<Map<String, dynamic>>(onCancel: () => ch.sink.close());
    ch.stream.listen(
      (m) {
        try {
          ctrl.add(Map<String, dynamic>.from(jsonDecode(m as String) as Map));
        } catch (_) {}
      },
      onError: (e) => ctrl.addError(AgentException('日志连接中断')),
      onDone: () => ctrl.close(),
    );
    return ctrl.stream;
  }

  void close() => _http.close();
}
