// 断线恢复测试：部署进行到一半时掐断 SSH（模拟 App 切后台/断网），部署必须在服务器上继续，
// App 重连后接着读进度直至完成；再模拟“App 被回收后重新打开”：attach 回放日志拿到结果。
// E2E_HOST=127.0.0.1 E2E_PORT=2222 E2E_USER=root E2E_PASS=... E2E_FP=SHA256:... flutter test test/e2e_resume_test.dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nailong/core/installer.dart';
import 'package:nailong/core/ssh.dart';
import 'package:nailong/core/store.dart';

void main() {
  final env = Platform.environment;
  final host = env['E2E_HOST'];
  final skip = host == null ? '未设置 E2E_HOST' : null;
  final port = int.tryParse(env['E2E_PORT'] ?? '22') ?? 22;
  final target = SshTarget(host: host ?? '', port: port, user: env['E2E_USER'] ?? 'root', password: env['E2E_PASS']);
  final fp = env['E2E_FP'] ?? '';

  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
  });

  test(
    '部署中掐断 SSH：服务器继续跑，重连后接上，直到完成',
    () async {
      var ssh = await SshSession.connect(target, knownFingerprint: fp, decide: (a, b, c) => false);
      var reconnects = 0;
      late ServerInstaller inst;
      inst = ServerInstaller(
        ssh,
        reconnect: () async {
          reconnects++;
          return SshSession.connect(target, knownFingerprint: fp, decide: (a, b, c) => false, retries: 0);
        },
      );
      await inst.ensureBundle();

      final events = <InstallerEvent>[];
      var dropped = 0;
      await for (final ev in inst.deploy({'ssh_user': target.user, 'sources': SourceSettings().forInstaller(), 'fail2ban': true})) {
        events.add(ev);
        if (ev.type == 'step_done') stdout.writeln('step_done ${ev.id} ${ev.data['status']} ${ev.data['message']}');
        if (ev.type == 'reconnecting') stdout.writeln('>> ${ev.data['message']}');
        // 每次进入 docker / images / agent 步骤时掐一次连接（模拟切后台）
        if (ev.type == 'step_start' && ['docker', 'images', 'agent'].contains(ev.id)) {
          dropped++;
          stdout.writeln('>> 掐断 SSH（第 $dropped 次，步骤 ${ev.id}）');
          inst.ssh.close();
        }
      }
      final result = events.lastWhere((e) => e.type == 'result').data;
      expect(result['ok'], isTrue, reason: '$result');
      expect(dropped, 3);
      expect(reconnects, greaterThanOrEqualTo(3), reason: '每次断线都应重连');
      expect(events.where((e) => e.type == 'reconnecting').length, greaterThanOrEqualTo(3), reason: '断线时界面必须收到提示');
      // 没有重复的步骤完成事件（偏移续读，不重复回放）
      final done = events.where((e) => e.type == 'step_done').map((e) => e.id).toList();
      expect(done.toSet().length, done.length, reason: '步骤事件不应重复：$done');
      expect(
        done,
        containsAll(['deps', 'fail2ban', 'docker', 'images', 'astrbot', 'napcat', 'onebot', 'agent', 'verify']),
      );
      // 服务器上没有残留的部署进程
      final r = await inst.ssh.run(
        '[ -e /opt/nailong/run/installer.pid ] && echo running || echo none; systemctl is-active nailong-deploy || true',
        sudo: false,
      );
      expect(r.stdout.split('\n').first.trim(), 'none', reason: '部署结束后不应有残留进程：${r.stdout}');

      // “App 被回收后重新打开”：用全新的安装器对象 attach，从头回放日志，直接拿到结果
      final fresh = ServerInstaller(inst.ssh);
      final replay = await fresh.deploy({}, attach: true).toList();
      expect(replay.last.type, 'result');
      expect(replay.last.data['ok'], isTrue);
      expect(replay.where((e) => e.type == 'step_done').length, done.length);
      inst.ssh.close();
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 30)),
  );
}
