import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart' show rootBundle;

import 'errors.dart';
import 'ssh.dart';

const remoteInstallerDir = '/opt/nailong/installer';
const _installer = 'python3 $remoteInstallerDir/nailong_installer.py';

class InstallerEvent {
  final String type;
  final Map<String, dynamic> data;

  InstallerEvent(this.type, this.data);

  String get id => data['id']?.toString() ?? '';
}

class Preflight {
  final String arch;
  final String osId;
  final String osVersion;
  final String osPretty;
  final bool hasPython;
  final bool hasApt;

  Preflight(this.arch, this.osId, this.osVersion, this.osPretty, this.hasPython, this.hasApt);
}

String _rand() => List.generate(10, (_) => Random.secure().nextInt(36).toRadixString(36)).join();

/// 服务器端安装器的 App 侧封装。所有命令参数都由 App 生成并做格式校验，
/// 不拼接任何用户输入到 shell 中（用户名、公钥另做白名单校验）。
class ServerInstaller {
  SshSession ssh;

  /// SSH 断开后（手机切后台、断网）用它重建连接。
  final Future<SshSession> Function()? reconnect;

  ServerInstaller(this.ssh, {this.reconnect});

  bool _watching = false;

  Future<Preflight> preflight() async {
    final r = await ssh.run(
      'uname -m; (. /etc/os-release 2>/dev/null; echo "\$ID|\$VERSION_ID|\$PRETTY_NAME"); '
      'command -v python3 >/dev/null && echo HAS_PY || echo NO_PY; '
      'command -v apt-get >/dev/null && echo HAS_APT || echo NO_APT',
      sudo: false,
    );
    final lines = r.stdout.split('\n');
    final os = (lines.length > 1 ? lines[1] : '').split('|');
    return Preflight(
      lines.first.trim(),
      os.isNotEmpty ? os[0] : '',
      os.length > 1 ? os[1] : '',
      os.length > 2 ? os[2] : '',
      r.stdout.contains('HAS_PY'),
      r.stdout.contains('HAS_APT'),
    );
  }

  /// 少数精简系统没有 python3：用系统包管理器安装（官方源，签名校验由 apt 完成）。
  Future<void> installPython(void Function(String) onLine) async {
    final code = await ssh.stream(
      'export DEBIAN_FRONTEND=noninteractive; apt-get update -q && apt-get install -y -q --no-install-recommends python3',
      onLine: onLine,
    );
    if (code != 0) throw NailongError('APT_FAILED', '安装 Python 3 失败，请检查服务器网络');
  }

  /// 上传安装包并在服务器上校验 SHA-256 后解压（已是同一版本则跳过）。
  Future<void> ensureBundle({void Function(String)? onStatus}) async {
    final meta = jsonDecode(await rootBundle.loadString('assets/server/bundle.json')) as Map<String, dynamic>;
    final sha = meta['sha256'] as String;
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(sha)) throw NailongError('BUNDLE', '安装包损坏');
    final current = await ssh.run('cat $remoteInstallerDir/.bundle-sha256 2>/dev/null || true');
    if (current.stdout.trim() == sha) return;
    final bytes = (await rootBundle.load('assets/server/bundle.tar.gz')).buffer.asUint8List();
    if (sha256.convert(bytes).toString() != sha) throw NailongError('BUNDLE', '安装包损坏，请重新安装奶龙 App');
    onStatus?.call('上传部署组件（${(bytes.length / 1024).toStringAsFixed(0)} KB）');
    final tmp = '/tmp/nailong-bundle-${_rand()}.tar.gz';
    await ssh.upload(tmp, bytes);
    onStatus?.call('校验部署组件 SHA-256');
    final r = await ssh.run(
      'set -e; F=$tmp; echo "$sha  \$F" | sha256sum -c --quiet -; '
      'D=$remoteInstallerDir; rm -rf \$D.new; mkdir -p \$D.new; tar xzf \$F -C \$D.new --no-same-owner; '
      'echo $sha > \$D.new/.bundle-sha256; chmod -R go-w \$D.new; rm -rf \$D; mv \$D.new \$D; rm -f \$F; echo BUNDLE_OK',
    );
    if (!r.stdout.contains('BUNDLE_OK')) {
      await ssh.run('rm -f $tmp', sudo: false);
      throw NailongError('BUNDLE', '部署组件校验失败（SHA-256 不一致），已停止', r.stderr);
    }
  }

  Map<String, dynamic> _result(String out) {
    final line = out.split('\n').lastWhere((l) => l.startsWith('@@RESULT '), orElse: () => '');
    if (line.isEmpty) {
      throw NailongError('INSTALLER', '服务器安装器没有返回结果', out.length > 500 ? out.substring(out.length - 500) : out);
    }
    final r = Map<String, dynamic>.from(jsonDecode(line.substring(9)) as Map);
    if (r['ok'] != true) {
      final code = r['code']?.toString() ?? 'INSTALLER';
      throw NailongError(
        code,
        r['message']?.toString() ?? installerHints[code] ?? '操作失败',
        r['detail']?.toString() ?? '',
      );
    }
    return r;
  }

  Future<Map<String, dynamic>> detect() async {
    final r = await ssh.run('$_installer detect', timeout: const Duration(minutes: 3));
    return Map<String, dynamic>.from(_result(r.stdout)['report'] as Map);
  }

  InstallerEvent? _parseLine(String line) {
    try {
      if (line.startsWith('@@EVENT ')) {
        final m = Map<String, dynamic>.from(jsonDecode(line.substring(8)) as Map);
        return InstallerEvent(m['type']?.toString() ?? 'log', m);
      }
      if (line.startsWith('@@RESULT ')) {
        return InstallerEvent('result', Map<String, dynamic>.from(jsonDecode(line.substring(9)) as Map));
      }
    } catch (_) {}
    return null;
  }

  /// 确保 SSH 可用；断开则按退避重连，最多约 15 分钟。
  Future<bool> _ensureConnected({required void Function(int attempt) onAttempt}) async {
    if (!ssh.isClosed) return true;
    if (reconnect == null) return false;
    for (var i = 0; i < 40; i++) {
      onAttempt(i + 1);
      try {
        ssh = await reconnect!();
        return true;
      } on NailongError catch (e) {
        if (e.code == 'AUTH_FAILED' || e.code.startsWith('HOSTKEY')) return false;
      } catch (_) {}
      await Future.delayed(Duration(seconds: [2, 3, 5, 8, 12, 20, 30][i < 7 ? i : 6]));
    }
    return false;
  }

  /// 在服务器上启动独立的后台部署，并持续读取进度。
  /// 部署进程与 SSH 连接无关：手机切后台、断网、甚至 App 被回收，部署都会继续；
  /// 重新连接后从上次位置接着读（attach=true 则从头回放日志，用于重新打开 App 后接上）。
  /// 最后一个事件 type=result。
  Stream<InstallerEvent> deploy(Map<String, dynamic> config, {bool attach = false}) async* {
    _watching = true;
    var offset = 0;
    try {
      if (!attach) {
        final cfgPath = '/tmp/nailong-deploy-${_rand()}.json';
        await ssh.upload(cfgPath, utf8.encode(jsonEncode(config)));
        final r = await ssh.run('$_installer deploy-start --config $cfgPath; R=\$?; rm -f $cfgPath; exit \$R');
        _result(r.stdout);
      }
      var failures = 0;
      var emptyAfterStop = 0;
      while (_watching) {
        try {
          if (ssh.isClosed) {
            // 连接断了（切后台、断网）：部署还在服务器上跑，先告诉界面，再尝试重连
            if (reconnect == null) throw NailongError('DISCONNECTED', '与服务器的连接已断开');
            yield InstallerEvent('reconnecting', {'message': '与服务器的连接中断，部署仍在服务器上继续，正在自动重连…', 'failures': failures});
            ssh = await reconnect!();
          }
          final r = await ssh.run('$_installer deploy-poll --offset $offset', timeout: const Duration(seconds: 25));
          failures = 0;
          bool running = true;
          for (final line in r.stdout.split('\n')) {
            if (line.startsWith('@@POLL ')) {
              final m = Map<String, dynamic>.from(jsonDecode(line.substring(7)) as Map);
              offset = (m['offset'] as num).toInt();
              running = m['running'] == true;
              continue;
            }
            final ev = _parseLine(line);
            if (ev != null) {
              yield ev;
              if (ev.type == 'result') return;
            } else if (line.trim().isNotEmpty) {
              yield InstallerEvent('log', {'line': line});
            }
          }
          if (!running) {
            // 进程已结束但没读到结果：再读一轮排空日志，仍没有就判定异常退出
            if (++emptyAfterStop >= 2) {
              yield InstallerEvent('result', {
                'ok': false,
                'code': 'PROCESS_EXITED',
                'message': '服务器上的部署进程意外退出，已完成的步骤会保留，可以继续部署',
              });
              return;
            }
          } else {
            emptyAfterStop = 0;
          }
        } on NailongError catch (e) {
          if (e.code == 'AUTH_FAILED' || e.code.startsWith('HOSTKEY')) {
            yield InstallerEvent('result', {'ok': false, 'code': e.code, 'message': e.message, 'detail': e.detail});
            return;
          }
          failures++;
          try {
            ssh.close();
          } catch (_) {}
        } catch (_) {
          failures++;
          try {
            ssh.close();
          } catch (_) {}
        }
        if (failures > 60) {
          yield InstallerEvent('result', {
            'ok': false,
            'code': 'DISCONNECTED',
            'message': '长时间连不上服务器。部署仍可能在服务器上继续，网络恢复后重新连接即可接上进度',
          });
          return;
        }
        await Future.delayed(
          failures == 0 ? const Duration(milliseconds: 1200) : Duration(seconds: failures < 4 ? 2 : 5),
        );
      }
    } on NailongError catch (e) {
      yield InstallerEvent('result', {'ok': false, 'code': e.code, 'message': e.message, 'detail': e.detail});
    } finally {
      _watching = false;
    }
  }

  void stopWatching() => _watching = false;

  /// 安全取消：通知服务器上的部署在当前原子步骤结束后停止。
  Future<void> cancel() async {
    await _ensureConnected(onAttempt: (_) {});
    await ssh.run('$_installer cancel', timeout: const Duration(seconds: 30));
  }

  bool get running => _watching;

  static final _userRe = RegExp(r'^[a-z_][a-z0-9_\-.]{0,31}$');
  static final _pubRe = RegExp(r'^ssh-ed25519 [A-Za-z0-9+/]{68}={0,2}$');
  static final _devRe = RegExp(r'^[a-z0-9][a-z0-9\-]{7,63}$');

  Future<void> authorizeKey({
    required String user,
    required String publicLine,
    required String deviceId,
    required int port,
  }) async {
    if (!_userRe.hasMatch(user) ||
        !_pubRe.hasMatch(publicLine) ||
        !_devRe.hasMatch(deviceId) ||
        port < 1024 ||
        port > 65535) {
      throw NailongError('BAD_INPUT', '参数不合法');
    }
    final r = await ssh.run(
      "$_installer authorize-key --user $user --pubkey '$publicLine' --device-id $deviceId --port $port",
    );
    _result(r.stdout);
  }

  Future<void> revokeKey({required String user, required String deviceId}) async {
    if (!_userRe.hasMatch(user) || !_devRe.hasMatch(deviceId)) throw NailongError('BAD_INPUT', '参数不合法');
    _result((await ssh.run('$_installer revoke-key --user $user --device-id $deviceId')).stdout);
  }

  Future<String> pairCode() async {
    final r = _result((await ssh.run('$_installer pair-code')).stdout);
    return r['code'] as String;
  }

  Future<List<Map<String, dynamic>>> speedtest(Map<String, dynamic> config, {bool fresh = false}) async {
    final p = '/tmp/nailong-speed-${_rand()}.json';
    await ssh.upload(p, utf8.encode(jsonEncode(config)));
    final r = await ssh.run(
      '$_installer speedtest --config $p ${fresh ? '--fresh' : ''}; rm -f $p',
      timeout: const Duration(minutes: 3),
    );
    return (_result(r.stdout)['registries'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }
}
