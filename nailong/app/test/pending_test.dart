import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nailong/core/ssh.dart';
import 'package:nailong/core/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 用内存实现替换 Android Keystore 通道，测试暂存的部署信息：保存、重启后恢复、过期、清除。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final secure = <String, String>{};

  setUp(() {
    secure.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
      (call) async {
        final args = Map<String, dynamic>.from((call.arguments ?? {}) as Map);
        final key = args['key'] as String?;
        switch (call.method) {
          case 'write':
            secure[key!] = args['value'] as String;
            return null;
          case 'read':
            return secure[key];
          case 'delete':
            secure.remove(key);
            return null;
          case 'containsKey':
            return secure.containsKey(key);
          case 'readAll':
            return secure;
        }
        return null;
      },
    );
  });

  const t = SshTarget(host: '1.2.3.4', port: 2222, user: 'root', password: 'S3cret!pass');

  test('部署中暂存连接信息，重启后能恢复（App 被系统回收的场景）', () async {
    SharedPreferences.setMockInitialValues({});
    final a = AppStore();
    await a.load();
    expect(a.pending, isNull);
    await a.setPending(t, savePassword: true);
    expect(secure['pend:pw'], 'S3cret!pass');
    // 模拟进程被杀后重新启动：全新的 AppStore 从磁盘恢复
    final b = AppStore();
    await b.load();
    expect(b.pending, isNotNull);
    expect(b.pending!.target.host, '1.2.3.4');
    expect(b.pending!.target.port, 2222);
    expect(b.pending!.target.password, 'S3cret!pass');
    expect(b.pending!.savePassword, isTrue);
  });

  test('部署结束后连接信息被删除，重启后不再恢复；SharedPreferences 里没有明文密码', () async {
    SharedPreferences.setMockInitialValues({});
    final a = AppStore();
    await a.load();
    await a.setPending(t, savePassword: false);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('pendingDeploy'), isNot(contains('S3cret')));
    await a.finishPending();
    expect(secure.keys.where((k) => k.startsWith('pend:')), isEmpty);
    final b = AppStore();
    await b.load();
    expect(b.pending, isNull);
  });

  test('clearPending 清除内存与磁盘并通知界面', () async {
    SharedPreferences.setMockInitialValues({});
    final a = AppStore();
    await a.load();
    await a.setPending(t, savePassword: false);
    var notified = 0;
    a.addListener(() => notified++);
    await a.clearPending();
    expect(a.pending, isNull);
    expect(notified, 1);
    expect((await SharedPreferences.getInstance()).getString('pendingDeploy'), isNull);
  });

  test('超过 12 小时的暂存信息自动作废并删除', () async {
    final old = DateTime.now().subtract(const Duration(hours: 13)).millisecondsSinceEpoch;
    SharedPreferences.setMockInitialValues({
      'pendingDeploy': jsonEncode({'host': '1.2.3.4', 'port': 22, 'user': 'root', 'savePassword': false, 'at': old}),
    });
    secure['pend:pw'] = 'old-password';
    final a = AppStore();
    await a.load();
    expect(a.pending, isNull);
    expect(secure.containsKey('pend:pw'), isFalse);
  });
}
