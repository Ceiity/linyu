// “App 被系统杀掉”场景：部署进行到一半丢弃全部内存状态（模拟进程被回收），
// 然后用全新的状态重启：从暂存的连接信息自动恢复 → 检测到部署仍在服务器上运行 → 接上 → 完成 → 配对。
// E2E_HOST=127.0.0.1 E2E_PORT=2222 E2E_USER=root E2E_PASS=... E2E_FP=SHA256:... flutter test test/e2e_killed_app_test.dart
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nailong/core/deploy_flow.dart';
import 'package:nailong/core/ssh.dart';
import 'package:nailong/core/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  final env = Platform.environment;
  final host = env['E2E_HOST'];
  final skip = host == null ? '未设置 E2E_HOST' : null;
  final port = int.tryParse(env['E2E_PORT'] ?? '22') ?? 22;
  final fp = env['E2E_FP'] ?? '';
  final secure = <String, String>{};

  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    HttpOverrides.global = null; // 允许真实网络（访问隧道）
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
      (call) async {
        final a = Map<String, dynamic>.from((call.arguments ?? {}) as Map);
        switch (call.method) {
          case 'write':
            secure[a['key'] as String] = a['value'] as String;
            return null;
          case 'read':
            return secure[a['key']];
          case 'delete':
            secure.remove(a['key']);
            return null;
          case 'readAll':
            return secure;
        }
        return null;
      },
    );
  });

  test(
    '部署中 App 被杀：重启后自动接上并完成配对',
    () async {
      SharedPreferences.setMockInitialValues({});
      final target = SshTarget(host: host!, port: port, user: env['E2E_USER'] ?? 'root', password: env['E2E_PASS']);

      // ---- 第一个“进程”：开始部署
      final store1 = AppStore();
      await store1.load();
      var flow1 = DeployFlow(store1);
      await flow1.connectAndDetect(target, (t, f, k) {
        expect(f, fp, reason: '首次连接展示的指纹要和服务器一致');
        return true;
      });
      expect(flow1.phase, FlowPhase.report, reason: '${flow1.error}');
      final running = flow1.deploy(); // 不 await：部署进行中
      for (var i = 0; i < 120 && flow1.step('docker').status != StepStatus.running; i++) {
        await Future.delayed(const Duration(milliseconds: 500));
      }
      expect(flow1.step('docker').status, StepStatus.running, reason: '应在安装 Docker 时“被杀”');
      stdout.writeln('>> 模拟 App 被系统杀掉（docker 步骤进行中）');
      flow1.dispose(); // 丢弃全部内存状态、关闭 SSH
      await running.timeout(const Duration(seconds: 60), onTimeout: () {});

      // 服务器上部署还在继续
      final probe = await SshSession.connect(target, knownFingerprint: fp, decide: (a, b, c) => false);
      final alive = await probe.run('[ -e /opt/nailong/run/installer.pid ] && echo running || echo none', sudo: false);
      probe.close();
      expect(alive.stdout.trim(), 'running', reason: 'App 被杀后服务器上的部署必须仍在运行');

      // ---- 第二个“进程”：全新状态重启
      final store2 = AppStore();
      await store2.load();
      expect(store2.pending, isNotNull, reason: '重启后要能恢复部署中的连接信息');
      stdout.writeln('>> 重启：恢复暂存连接信息 ${store2.pending!.target.user}@${store2.pending!.target.host}');
      final flow2 = DeployFlow(store2);
      await flow2.connectAndDetect(store2.pending!.target, (a, b, c) => false); // 已信任指纹，不应再询问
      expect(flow2.phase, FlowPhase.success, reason: '${flow2.error} ${flow2.error?.detail}');
      for (final id in [
        'deps',
        'fail2ban',
        'docker',
        'images',
        'astrbot',
        'napcat',
        'onebot',
        'agent',
        'verify',
        'pair',
        'tunnel',
      ]) {
        final st = flow2.step(id).status;
        expect([StepStatus.done, StepStatus.kept, StepStatus.skipped], contains(st), reason: '$id: $st');
      }
      expect(store2.servers, isNotEmpty);
      expect(secure['token:${store2.current!.id}'], isNotNull, reason: '应已保存访问令牌');
      expect(secure.keys.where((k) => k.startsWith('pend:')), isEmpty, reason: '完成后暂存的连接信息必须删除');
      flow2.dispose();
    },
    skip: skip,
    timeout: const Timeout(Duration(minutes: 30)),
  );
}
