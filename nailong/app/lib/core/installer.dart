import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:dartssh2/dartssh2.dart';
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
  final SshSession ssh;
  SSHSession? _running;

  ServerInstaller(this.ssh);

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

  /// 执行部署，事件流逐条返回；最后一个事件 type=result。
  Stream<InstallerEvent> deploy(Map<String, dynamic> config) {
    final ctrl = StreamController<InstallerEvent>();
    () async {
      try {
        final cfgPath = '/tmp/nailong-deploy-${_rand()}.json';
        await ssh.upload(cfgPath, utf8.encode(jsonEncode(config)));
        final code = await ssh.stream(
          '$_installer deploy --config $cfgPath; R=\$?; rm -f $cfgPath; exit \$R',
          onStart: (s) => _running = s,
          onLine: (line) {
            if (line.startsWith('@@EVENT ')) {
              try {
                final m = Map<String, dynamic>.from(jsonDecode(line.substring(8)) as Map);
                ctrl.add(InstallerEvent(m['type']?.toString() ?? 'log', m));
              } catch (_) {}
            } else if (line.startsWith('@@RESULT ')) {
              ctrl.add(InstallerEvent('result', Map<String, dynamic>.from(jsonDecode(line.substring(9)) as Map)));
            } else if (line.trim().isNotEmpty) {
              ctrl.add(InstallerEvent('log', {'line': line}));
            }
          },
        );
        if (code == -1 && !ctrl.isClosed) {
          ctrl.add(
            InstallerEvent('result', {
              'ok': false,
              'code': 'DISCONNECTED',
              'message': '与服务器的连接中断，部署在服务器上可能仍在进行，可稍后继续部署',
            }),
          );
        }
      } catch (e) {
        ctrl.add(InstallerEvent('result', {'ok': false, 'code': 'SSH_ERROR', 'message': e.toString()}));
      } finally {
        _running = null;
        await ctrl.close();
      }
    }();
    return ctrl.stream;
  }

  /// 安全取消：通知安装器在当前原子步骤结束后停止。
  Future<void> cancel() async {
    await ssh.run('$_installer cancel', timeout: const Duration(seconds: 30));
  }

  bool get running => _running != null;

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
