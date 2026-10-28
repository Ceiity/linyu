// 生成界面截图：SCREENSHOTS=1 flutter test test/screenshot_test.dart --update-goldens
// 使用真实页面代码 + 假 Agent 数据（结构与真实 Agent 返回一致），输出到 test/goldens/。
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nailong/core/agent_api.dart';
import 'package:nailong/core/connection.dart';
import 'package:nailong/core/deploy_flow.dart';
import 'package:nailong/core/ssh.dart';
import 'package:nailong/core/store.dart';
import 'package:nailong/pages/conn_scope.dart';
import 'package:nailong/pages/dashboard_page.dart';
import 'package:nailong/pages/deploy_page.dart';
import 'package:nailong/pages/logs_page.dart';
import 'package:nailong/pages/more_page.dart';
import 'package:nailong/pages/plugins_page.dart';
import 'package:nailong/pages/qq_page.dart';
import 'package:nailong/pages/welcome_page.dart';
import 'package:nailong/ui/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeAgent extends AgentApi {
  int tick = 0;

  FakeAgent() : super(0, token: 'x');

  @override
  Future<dynamic> get(String path, {Map<String, String>? query, Duration timeout = const Duration(seconds: 30)}) async {
    tick++;
    if (path == '/api/overview') {
      return {
        'agent_version': '1.0.0',
        'hostname': 'nailong-demo',
        'server': {'os': 'Ubuntu 24.04.5 LTS', 'arch': 'amd64', 'hostname': 'nailong-demo'},
        'docker': {'ok': true, 'version': '29.9.2'},
        'astrbot': {'container': 'astrbot', 'state': 'running', 'running': true, 'image': 'soulter/astrbot:v4.29.3'},
        'napcat': [
          {'container': 'napcat', 'state': 'running', 'running': true},
        ],
        'metrics': {
          'cpu_percent': 23.4, 'cpu_cores': 2, 'load': [0.42, 0.38, 0.31], 'mem_total': 4 * 1073741824,
          'mem_used': 2.3 * 1073741824, 'mem_percent': 57.5, 'disk_total': 60 * 1073741824, 'disk_used': 17.2 * 1073741824,
          'disk_percent': 28.7, 'net_rx_bps': 186000 + tick * 9000, 'net_tx_bps': 42000 + tick * 3000, 'uptime': 3 * 86400 + 5 * 3600,
        },
      };
    }
    if (path == '/api/napcat') {
      return [
        {'container': 'napcat', 'state': 'running', 'running': true},
      ];
    }
    if (path.endsWith('/login')) {
      return {
        'name': 'napcat', 'is_login': false, 'is_offline': false, 'error': '', 'phase': 'qrcode',
        'qrcode': 'https://txz.qq.com/p?k=nailong-demo-qrcode&f=1600001604',
      };
    }
    if (path == '/api/plugins') {
      return [
        {'name': 'astrbot_plugin_weather', 'display_name': '天气查询', 'desc': '查询城市实时天气与未来三天预报', 'author': 'demo', 'version': '1.2.0', 'repo': 'https://github.com/demo/astrbot_plugin_weather', 'activated': true, 'reserved': false, 'has_update': true, 'online_version': '1.3.0'},
        {'name': 'astrbot_plugin_daily_news', 'display_name': '每日新闻', 'desc': '每天早上推送 60 秒读懂世界', 'author': 'demo', 'version': '0.4.1', 'repo': '', 'activated': true, 'reserved': false, 'has_update': false, 'online_version': ''},
        {'name': 'astrbot_plugin_sign', 'display_name': '群签到', 'desc': '群内签到、积分与排行榜', 'author': 'demo', 'version': '2.0.0', 'repo': '', 'activated': false, 'reserved': false, 'has_update': false, 'online_version': ''},
        {'name': 'builtin_commands', 'display_name': 'builtin_commands', 'desc': "AstrBot's internal plugin, providing all built-in commands such as /reset.", 'author': 'Soulter', 'version': '0.0.1', 'repo': '', 'activated': true, 'reserved': true, 'has_update': false, 'online_version': ''},
      ];
    }
    return {};
  }

  @override
  Stream<Map<String, dynamic>> logStream(String target, {int tail = 300}) {
    final lines = <Map<String, dynamic>>[
      {'time': '2026-10-28 07:31:02', 'level': 'INFO', 'text': '[Core] [INFO] AstrBot v4.29.3 启动完成', 'hint': ''},
      {'time': '2026-10-28 07:31:03', 'level': 'INFO', 'text': '[Core] [INFO] 插件 天气查询 载入成功', 'hint': '插件已加载'},
      {'time': '2026-10-28 07:31:05', 'level': 'INFO', 'text': '[Platform] [INFO] aiocqhttp(OneBot v11) 适配器已连接 napcat', 'hint': 'NapCat 已连接到 AstrBot'},
      {'time': '2026-10-28 07:32:11', 'level': 'WARNING', 'text': '[Core] [WARN] 会话 123456 触发速率限制，已排队', 'hint': ''},
      {'time': '2026-10-28 07:33:40', 'level': 'ERROR', 'text': '[Provider] [ERRO] 调用模型失败：Authorization: Bearer ****** 返回 429', 'hint': ''},
      {'time': '2026-10-28 07:33:41', 'level': 'INFO', 'text': '[Provider] [INFO] 已自动切换到备用模型', 'hint': ''},
      {'time': '2026-10-28 07:34:02', 'level': 'DEBUG', 'text': '[Core] [DEBG] 消息处理耗时 182ms', 'hint': ''},
    ];
    return Stream.fromIterable(lines);
  }
}

Future<void> loadFonts() async {
  final cjk = File('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc').readAsBytesSync();
  final sdk = Platform.environment['FLUTTER_ROOT'] ?? '/opt/sdk/flutter';
  final icons = File('$sdk/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf').readAsBytesSync();
  final roboto = File('$sdk/bin/cache/artifacts/material_fonts/Roboto-Regular.ttf').readAsBytesSync();
  for (final family in ['Roboto', '.SF Pro Text', 'sans-serif', 'monospace']) {
    await (FontLoader(family)
          ..addFont(Future.value(ByteData.view(roboto.buffer)))
          ..addFont(Future.value(ByteData.view(cjk.buffer))))
        .load();
  }
  await (FontLoader('WQY')..addFont(Future.value(ByteData.view(cjk.buffer)))).load();
  await (FontLoader('MaterialIcons')..addFont(Future.value(ByteData.view(icons.buffer)))).load();
}

void main() {
  final skip = Platform.environment['SCREENSHOTS'] == null ? '设置 SCREENSHOTS=1 生成截图' : null;
  late AppStore store;
  late ServerConnection conn;

  setUpAll(() async {
    if (skip != null) return;
    await loadFonts();
    SharedPreferences.setMockInitialValues({});
    store = AppStore();
    await store.load();
    final p = ServerProfile(
      id: 'demo', name: '我的服务器', host: '123.123.123.123', port: 22, user: 'root',
      hostKey: 'SHA256:x', agentPort: 18180, deviceId: 'nl-demo00001', lastOnline: DateTime.now().millisecondsSinceEpoch,
    );
    store.servers = [p];
    store.currentId = 'demo';
    conn = ServerConnection(store, p)
      ..api = FakeAgent()
      ..state = ConnState.online;
  });

  Widget app(Widget child, {bool dark = false}) {
    final (light, darkCs) = appSchemes(brandYellow);
    ThemeData t(ColorScheme cs) {
      final base = buildTheme(cs);
      return base.copyWith(textTheme: base.textTheme.apply(fontFamily: 'WQY'), primaryTextTheme: base.primaryTextTheme.apply(fontFamily: 'WQY'));
    }

    return StoreScope(
      store: store,
      child: ConnScope(
        conn: conn,
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: t(light),
          darkTheme: t(darkCs),
          themeMode: dark ? ThemeMode.dark : ThemeMode.light,
          home: DefaultTextStyle.merge(style: const TextStyle(fontFamily: 'WQY'), child: child),
        ),
      ),
    );
  }

  Future<void> shot(WidgetTester tester, String name, Widget page, {bool dark = false, Future<void> Function()? after}) async {
    tester.view.physicalSize = const Size(1170, 2532);
    tester.view.devicePixelRatio = 3;
    await tester.runAsync(() async {
      await tester.pumpWidget(app(page, dark: dark));
      for (var i = 0; i < 6; i++) {
        await Future.delayed(const Duration(milliseconds: 200));
        await tester.pump(const Duration(milliseconds: 200));
      }
      if (after != null) await after();
      for (final el in find.byType(Image).evaluate()) {
        final img = (el.widget as Image).image;
        await precacheImage(img, el);
      }
      await tester.pump(const Duration(milliseconds: 300));
    });
    await tester.pumpAndSettle(const Duration(milliseconds: 100), EnginePhase.sendSemanticsUpdate, const Duration(seconds: 3)).catchError((_) => 0);
    await expectLater(find.byType(MaterialApp), matchesGoldenFile('goldens/$name.png'));
  }

  DeployFlow flowWith(String fixture, FlowPhase phase) {
    final f = DeployFlow(store)..target = const SshTarget(host: '123.123.123.123');
    f.report = Map<String, dynamic>.from(jsonDecode(File('test/fixtures/$fixture').readAsStringSync()) as Map);
    f.phase = phase;
    return f;
  }

  testWidgets('01 欢迎页', (t) => shot(t, '01_welcome', const WelcomePage()), skip: skip != null);

  testWidgets('02 环境报告（全新服务器）', (t) => shot(t, '02_report_fresh', DeployPage(target: const SshTarget(host: '123.123.123.123'), debugFlow: flowWith('report_fresh.json', FlowPhase.report))), skip: skip != null);

  testWidgets('03 环境报告（接管已有）', (t) => shot(t, '03_report_takeover', DeployPage(target: const SshTarget(host: '123.123.123.123'), debugFlow: flowWith('report_takeover.json', FlowPhase.report))), skip: skip != null);

  testWidgets('04 部署中', (t) {
    final f = flowWith('report_fresh.json', FlowPhase.deploying);
    for (final id in ['connect', 'detect', 'deps', 'docker']) {
      f.step(id).status = StepStatus.done;
    }
    f.step('connect').message = '已连接（SHA256:7RWDvIkD/pdOWCZ…）';
    f.step('detect').message = 'Ubuntu 24.04.5 LTS · amd64';
    f.step('deps').message = '已安装：curl、gnupg';
    f.step('docker').message = 'Docker 29.9.2 已安装并设置开机启动';
    f.step('images')
      ..status = StepStatus.running
      ..percent = 46
      ..speed = 11800000
      ..message = '正在从 Docker Hub 拉取 soulter/astrbot:v4.29.3  412.6 MB / 896.3 MB';
    f.status = '正在从 Docker Hub 拉取 soulter/astrbot:v4.29.3';
    return shot(t, '04_deploying', DeployPage(target: const SshTarget(host: '123.123.123.123'), debugFlow: f));
  }, skip: skip != null);

  testWidgets('05 部署成功', (t) {
    final f = flowWith('report_fresh.json', FlowPhase.success);
    for (final s in f.steps) {
      s.status = StepStatus.done;
    }
    f.step('pair').message = '设备已授权';
    f.step('tunnel').message = '安全通道正常';
    f.result = store.servers.first;
    return shot(t, '05_success', DeployPage(target: const SshTarget(host: '123.123.123.123'), debugFlow: f));
  }, skip: skip != null);

  testWidgets('06 首页', (t) => shot(t, '06_dashboard', DashboardPage(active: true, onOpenLogs: (_) {}, onGo: (_) {})), skip: skip != null);

  testWidgets('07 首页深色', (t) => shot(t, '07_dashboard_dark', DashboardPage(active: true, onOpenLogs: (_) {}, onGo: (_) {}), ), skip: skip != null);

  testWidgets('08 QQ 登录', (t) => shot(t, '08_qq', const QqPage(active: true)), skip: skip != null);

  testWidgets('09 插件', (t) => shot(t, '09_plugins', PluginsPage(active: true, onOpenLogs: (_) {})), skip: skip != null);

  testWidgets('10 日志', (t) => shot(t, '10_logs', LogsPage(active: true, target: ValueNotifier(null))), skip: skip != null);

  testWidgets('11 更多', (t) => shot(t, '11_more', const MorePage(), ), skip: skip != null);
}
