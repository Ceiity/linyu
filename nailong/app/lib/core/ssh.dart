import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dartssh2/dartssh2.dart';

import 'errors.dart';

/// SSH 连接参数。密码/私钥只保存在内存，除非用户同意保存到 Android Keystore。
class SshTarget {
  final String host;
  final int port;
  final String user;
  final String? password;
  final String? privateKeyPem;
  final String? passphrase;

  const SshTarget({
    required this.host,
    this.port = 22,
    this.user = 'root',
    this.password,
    this.privateKeyPem,
    this.passphrase,
  });

  String get hostKeyId => '${host.toLowerCase()}:$port';

  SshTarget copyWith({String? password, String? privateKeyPem}) => SshTarget(
    host: host,
    port: port,
    user: user,
    password: password ?? this.password,
    privateKeyPem: privateKeyPem ?? this.privateKeyPem,
    passphrase: passphrase,
  );
}

/// 主机密钥校验：返回 true 表示信任。
/// [known] 为已保存的指纹（null 表示首次连接，需要用户确认）。
typedef HostKeyDecider = FutureOr<bool> Function(String type, String fingerprint, String? known);

/// dartssh2 传入的是 `SHA256:<base64>` 文本的字节；兼容原始摘要字节。结果与 `ssh-keygen -lf` 一致。
String formatFingerprint(Uint8List fp) {
  try {
    final text = utf8.decode(fp);
    if (text.startsWith('SHA256:')) return text;
  } catch (_) {}
  return 'SHA256:${base64.encode(fp).replaceAll('=', '')}';
}

class CommandResult {
  final int exitCode;
  final String stdout;
  final String stderr;

  CommandResult(this.exitCode, this.stdout, this.stderr);

  bool get ok => exitCode == 0;
}

class SshSession {
  final SshTarget target;
  final SSHClient client;
  final String hostKeyFingerprint;
  bool isRoot = false;
  bool sudoNoPassword = false;

  SshSession._(this.target, this.client, this.hostKeyFingerprint);

  Future<void> get done => client.done;

  bool get isClosed => client.isClosed;

  /// 连接并认证，失败时按次数重试（认证失败、主机密钥不符不重试）。
  static Future<SshSession> connect(
    SshTarget target, {
    required String? knownFingerprint,
    required HostKeyDecider decide,
    Duration timeout = const Duration(seconds: 12),
    int retries = 2,
    bool probePrivileges = true,
  }) async {
    Object? lastError;
    for (var attempt = 0; attempt <= retries; attempt++) {
      try {
        return await _connectOnce(target, knownFingerprint, decide, timeout, probePrivileges);
      } on NailongError catch (e) {
        if (e.code == 'AUTH_FAILED' || e.code == 'HOSTKEY_REJECTED' || e.code == 'HOSTKEY_CHANGED') rethrow;
        lastError = e;
      } catch (e) {
        lastError = e;
      }
      if (attempt < retries) await Future.delayed(Duration(seconds: 1 << attempt));
    }
    throw lastError is NailongError ? lastError : NailongError.fromSsh(lastError ?? 'unknown');
  }

  static Future<SshSession> _connectOnce(
    SshTarget target,
    String? known,
    HostKeyDecider decide,
    Duration timeout,
    bool probePrivileges,
  ) async {
    SSHSocket socket;
    try {
      socket = await SSHSocket.connect(target.host, target.port, timeout: timeout);
    } catch (e) {
      throw NailongError.fromSsh(e);
    }
    String fingerprint = '';
    String? hostKeyProblem;
    final identities = <SSHKeyPair>[];
    if (target.privateKeyPem != null && target.privateKeyPem!.trim().isNotEmpty) {
      try {
        identities.addAll(SSHKeyPair.fromPem(target.privateKeyPem!, target.passphrase));
      } catch (e) {
        socket.destroy();
        throw NailongError('BAD_KEY', '私钥无法解析，请检查私钥内容和密码', '$e');
      }
    }
    final client = SSHClient(
      socket,
      username: target.user,
      identities: identities.isEmpty ? null : identities,
      onPasswordRequest: target.password == null ? null : () => target.password!,
      keepAliveInterval: const Duration(seconds: 15),
      onVerifyHostKey: (type, fp) async {
        fingerprint = formatFingerprint(fp);
        if (known != null) {
          if (known == fingerprint) return true;
          hostKeyProblem = 'HOSTKEY_CHANGED';
          return false;
        }
        final ok = await decide(type, fingerprint, known);
        if (!ok) hostKeyProblem = 'HOSTKEY_REJECTED';
        return ok;
      },
    );
    try {
      await client.authenticated.timeout(timeout * 2);
    } catch (e) {
      client.close();
      if (hostKeyProblem == 'HOSTKEY_CHANGED') {
        throw NailongError(
          'HOSTKEY_CHANGED',
          '服务器身份与上次不一致！可能存在中间人攻击，已停止连接。若确认服务器重装过，请在服务器管理中“重新信任”。',
          '新指纹：$fingerprint',
        );
      }
      if (hostKeyProblem == 'HOSTKEY_REJECTED') {
        throw NailongError('HOSTKEY_REJECTED', '你拒绝了该服务器的身份，未建立连接');
      }
      throw NailongError.fromSsh(e);
    }
    final s = SshSession._(target, client, fingerprint);
    if (probePrivileges) await s._probePrivileges();
    return s;
  }

  Future<void> _probePrivileges() async {
    final r = await run('id -u; (sudo -n true >/dev/null 2>&1 && echo SUDO_NOPASS) || echo SUDO_NEEDPASS', sudo: false);
    isRoot = r.stdout.split('\n').first.trim() == '0';
    sudoNoPassword = r.stdout.contains('SUDO_NOPASS');
  }

  bool get canElevate => isRoot || sudoNoPassword || (target.password != null && target.password!.isNotEmpty);

  /// 以 root 运行时的命令前缀；密码通过 stdin 传给 sudo，不出现在命令行或日志中。
  String _wrap(String cmd, bool sudo) {
    if (!sudo || isRoot) return cmd;
    final escaped = cmd.replaceAll("'", "'\"'\"'");
    return sudoNoPassword ? "sudo -n sh -c '$escaped'" : "sudo -S -p '' sh -c '$escaped'";
  }

  void _feedSudo(SSHSession s, bool sudo) {
    if (sudo && !isRoot && !sudoNoPassword && target.password != null) {
      s.stdin.add(Uint8List.fromList(utf8.encode('${target.password}\n')));
    }
  }

  Future<CommandResult> run(String cmd, {bool sudo = true, Duration timeout = const Duration(minutes: 2)}) async {
    if (sudo && !canElevate) {
      throw NailongError('NO_ROOT', '需要 root 权限：请使用 root 登录，或使用有 sudo 权限的用户并填写密码');
    }
    final session = await client.execute(_wrap(cmd, sudo));
    _feedSudo(session, sudo);
    final out = BytesBuilder();
    final err = BytesBuilder();
    final a = session.stdout.listen(out.add).asFuture<void>();
    final b = session.stderr.listen(err.add).asFuture<void>();
    try {
      await Future.wait([a, b, session.done]).timeout(timeout);
    } on TimeoutException {
      session.close();
      throw NailongError('TIMEOUT', '服务器执行命令超时');
    }
    final stderr = utf8.decode(err.takeBytes(), allowMalformed: true);
    if (sudo && !isRoot && stderr.contains('incorrect password')) {
      throw NailongError('SUDO_FAILED', 'sudo 密码错误或该用户没有 sudo 权限');
    }
    return CommandResult(session.exitCode ?? -1, utf8.decode(out.takeBytes(), allowMalformed: true), stderr);
  }

  /// 流式执行，逐行回调 stdout。返回退出码。
  Future<int> stream(
    String cmd, {
    required void Function(String line) onLine,
    bool sudo = true,
    void Function(SSHSession session)? onStart,
  }) async {
    final session = await client.execute(_wrap(cmd, sudo));
    onStart?.call(session);
    _feedSudo(session, sudo);
    final lines = session.stdout.cast<List<int>>().transform(utf8.decoder).transform(const LineSplitter());
    final errLines = session.stderr.cast<List<int>>().transform(utf8.decoder).transform(const LineSplitter());
    final a = lines.listen(onLine).asFuture<void>();
    final b = errLines.listen((l) => onLine('[stderr] $l')).asFuture<void>();
    await Future.wait([a, b, session.done]);
    return session.exitCode ?? -1;
  }

  Future<void> upload(String remotePath, Uint8List data) async {
    final sftp = await client.sftp();
    try {
      final f = await sftp.open(
        remotePath,
        mode: SftpFileOpenMode.create | SftpFileOpenMode.truncate | SftpFileOpenMode.write,
      );
      await f.writeBytes(data);
      await f.close();
    } finally {
      sftp.close();
    }
  }

  /// 打开到服务器本机端口的转发通道（App ↔ Agent 的 SSH 隧道）。
  Future<SSHForwardChannel> forward(int remotePort) => client.forwardLocal('127.0.0.1', remotePort);

  void close() => client.close();
}

/// 本地端口 ↔ SSH 转发，让 http / WebSocket 客户端能直接访问 127.0.0.1:localPort。
class LocalTunnel {
  final SshSession session;
  final int remotePort;
  ServerSocket? _server;
  final _sockets = <Socket>{};

  LocalTunnel(this.session, this.remotePort);

  int get localPort => _server!.port;

  bool get isOpen => _server != null && !session.isClosed;

  Future<void> open() async {
    _server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    _server!.listen((socket) async {
      _sockets.add(socket);
      try {
        final ch = await session.forward(remotePort);
        socket.listen(
          (d) => ch.sink.add(d),
          onDone: () => ch.sink.close(),
          onError: (_) => ch.sink.close(),
          cancelOnError: true,
        );
        ch.stream.listen(
          socket.add,
          onDone: () => socket.destroy(),
          onError: (_) => socket.destroy(),
          cancelOnError: true,
        );
      } catch (_) {
        socket.destroy();
      } finally {
        socket.done.whenComplete(() => _sockets.remove(socket)).ignore();
      }
    });
  }

  Future<void> close() async {
    for (final s in _sockets.toList()) {
      s.destroy();
    }
    await _server?.close();
    _server = null;
  }
}
