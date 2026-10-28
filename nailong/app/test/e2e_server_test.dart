// 端到端测试：用 App 真实代码通过 SSH 部署一台全新服务器。
// 需要测试服务器：E2E_HOST=127.0.0.1 E2E_PORT=2222 E2E_USER=root E2E_PASS=... E2E_FP=SHA256:...
// flutter test test/e2e_server_test.dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nailong/core/agent_api.dart';
import 'package:nailong/core/errors.dart';
import 'package:nailong/core/installer.dart';
import 'package:nailong/core/keys.dart';
import 'package:nailong/core/ssh.dart';

void main() {
  final env = Platform.environment;
  final host = env['E2E_HOST'];
  final skip = host == null ? '未设置 E2E_HOST' : null;
  final port = int.tryParse(env['E2E_PORT'] ?? '22') ?? 22;
  final user = env['E2E_USER'] ?? 'root';
  final fp = env['E2E_FP'] ?? '';

  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    HttpOverrides.global = null; // 允许真实网络（访问隧道）
  });

  SshTarget target({String? pass}) => SshTarget(host: host!, port: port, user: user, password: pass ?? env['E2E_PASS']);

  test('首次连接需确认指纹；拒绝则不连接；密码错误给出中文提示', () async {
    String? shown;
    await expectLater(
      SshSession.connect(target(), knownFingerprint: null, decide: (t, f, k) {
        shown = f;
        return false;
      }, retries: 0),
      throwsA(isA<NailongError>().having((e) => e.code, 'code', 'HOSTKEY_REJECTED')),
    );
    expect(shown, fp, reason: 'App 显示的指纹必须与 ssh-keygen -lf 一致');
    await expectLater(
      SshSession.connect(target(), knownFingerprint: 'SHA256:forged', decide: (a, b, c) => true, retries: 0),
      throwsA(isA<NailongError>().having((e) => e.code, 'code', 'HOSTKEY_CHANGED')),
    );
    await expectLater(
      SshSession.connect(target(pass: 'wrong-password'), knownFingerprint: fp, decide: (a, b, c) => true, retries: 0),
      throwsA(isA<NailongError>().having((e) => e.code, 'code', 'AUTH_FAILED')),
    );
  }, skip: skip);

  test('全新服务器：检测 → 部署 → 配对 → 受限密钥隧道', () async {
    final ssh = await SshSession.connect(target(), knownFingerprint: fp, decide: (a, b, c) => false);
    expect(ssh.canElevate, isTrue);
    final inst = ServerInstaller(ssh);
    final pre = await inst.preflight();
    expect(pre.osId, 'ubuntu');
    await inst.ensureBundle();
    final report = await inst.detect();
    final plan = Map<String, dynamic>.from(report['plan'] as Map);
    stdout.writeln('部署模式：${plan['mode']}，阻塞：${plan['blockers']}');
    expect(plan['blockers'], isEmpty);

    final events = <InstallerEvent>[];
    await for (final ev in inst.deploy({'ssh_user': user, 'sources': {}})) {
      events.add(ev);
      if (ev.type == 'step_done' || ev.type == 'error') stdout.writeln('${ev.type} ${ev.id} ${ev.data['status'] ?? ''} ${ev.data['message']}');
    }
    final result = events.lastWhere((e) => e.type == 'result').data;
    expect(result['ok'], isTrue, reason: '$result');
    final agentPort = (result['agent_port'] as num).toInt();

    // 配对
    final key = DeviceKey.generate('nailong:nl-e2etest001');
    await inst.authorizeKey(user: user, publicLine: key.publicLine, deviceId: 'nl-e2etest001', port: agentPort);
    final code = await inst.pairCode();
    final t1 = LocalTunnel(ssh, agentPort);
    await t1.open();
    final pair = Map<String, dynamic>.from(await AgentApi(t1.localPort).post('/api/pair', {
      'code': code,
      'device_name': 'e2e',
      'device_id': 'nl-e2etest001',
    }) as Map);
    await t1.close();
    ssh.close();

    // 用受限密钥：只能隧道，不能执行命令
    final keySsh = await SshSession.connect(
      SshTarget(host: host!, port: port, user: user, privateKeyPem: key.privatePem),
      knownFingerprint: fp,
      decide: (a, b, c) => false,
      probePrivileges: false,
    );
    final r = await keySsh.run('id; cat /etc/shadow', sudo: false);
    expect(r.stdout.trim(), 'nailong-tunnel-only', reason: 'App 密钥不应能执行命令');
    await expectLater(keySsh.forward(22).then((c) => c.sink.close()), throwsA(anything), reason: '只能转发到 Agent 端口');
    final tunnel = LocalTunnel(keySsh, agentPort);
    await tunnel.open();
    final api = AgentApi(tunnel.localPort, token: pair['token'] as String);
    final me = Map<String, dynamic>.from(await api.get('/api/me') as Map);
    expect(me['device']['name'], 'e2e');
    final ov = Map<String, dynamic>.from(await api.get('/api/overview') as Map);
    expect(ov['astrbot']['running'], isTrue);
    expect((ov['napcat'] as List).first['running'], isTrue);
    stdout.writeln('指标：${ov['metrics']}');
    final plugins = await api.get('/api/plugins') as List;
    expect(plugins, isNotEmpty);
    final logs = await api.get('/api/logs', query: {'target': 'astrbot', 'tail': '50'}) as List;
    expect(logs, isNotEmpty);
    // WebSocket 实时日志
    final first = await api.logStream('astrbot', tail: 5).first.timeout(const Duration(seconds: 20));
    expect(first['text'], isNotNull);
    // 备份 → 校验
    final task = Map<String, dynamic>.from(await api.post('/api/backups', {'scopes': ['astrbot_config', 'napcat_config']}) as Map);
    final done = await api.watchTask(task['id'] as String).last;
    expect(done['status'], 'success', reason: '$done');
    final name = done['result']['name'] as String;
    final v = Map<String, dynamic>.from(await api.post('/api/backups/$name/verify') as Map);
    expect(v['files'], greaterThan(0));
    final bytes = await api.download('/api/backups/$name/download');
    expect(bytes.length, done['result']['size']);
    api.close();
    await tunnel.close();
    keySsh.close();
  }, skip: skip, timeout: const Timeout(Duration(minutes: 30)));
}
