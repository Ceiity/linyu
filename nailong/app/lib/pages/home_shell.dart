import 'package:material_ui/material_ui.dart';

import '../core/connection.dart';
import '../core/store.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';
import 'dashboard_page.dart';
import 'logs_page.dart';
import 'more_page.dart';
import 'plugins_page.dart';
import 'qq_page.dart';
import 'welcome_page.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

const _dests = [
  (Icons.space_dashboard_outlined, Icons.space_dashboard, '首页'),
  (Icons.qr_code_2_outlined, Icons.qr_code_2, 'QQ'),
  (Icons.extension_outlined, Icons.extension, '插件'),
  (Icons.receipt_long_outlined, Icons.receipt_long, '日志'),
  (Icons.widgets_outlined, Icons.widgets, '更多'),
];

class _HomeShellState extends State<HomeShell> {
  late ServerConnection conn;
  int index = 0;
  final logTarget = ValueNotifier<String?>(null);

  @override
  void initState() {
    super.initState();
    final store = StoreScope.read(context);
    conn = ServerConnection(store, store.current!)..connect();
  }

  @override
  void dispose() {
    conn.dispose();
    logTarget.dispose();
    super.dispose();
  }

  void go(int i) => setState(() => index = i);

  void openLogs(String target) {
    logTarget.value = target;
    go(3);
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardPage(active: index == 0, onOpenLogs: openLogs, onGo: go),
      QqPage(active: index == 1),
      PluginsPage(active: index == 2, onOpenLogs: openLogs),
      LogsPage(active: index == 3, target: logTarget),
      const MorePage(),
    ];
    return ConnScope(
      conn: conn,
      child: Scaffold(
        body: Column(
          children: [
            const _ConnBanner(),
            Expanded(
              child: IndexedStack(index: index, children: pages),
            ),
          ],
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: go,
          destinations: [
            for (final d in _dests) NavigationDestination(icon: Icon(d.$1), selectedIcon: Icon(d.$2), label: d.$3),
          ],
        ),
      ),
    );
  }
}

class _ConnBanner extends StatelessWidget {
  const _ConnBanner();

  @override
  Widget build(BuildContext context) {
    final c = ConnScope.of(context);
    final cs = Theme.of(context).colorScheme;
    if (c.state == ConnState.online || c.state == ConnState.idle) return const SizedBox.shrink();
    final unauthorized = c.state == ConnState.unauthorized;
    final (bg, fg) = unauthorized
        ? (cs.errorContainer, cs.onErrorContainer)
        : (cs.secondaryContainer, cs.onSecondaryContainer);
    return Material(
      color: bg,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(
            children: [
              if (!unauthorized)
                SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: fg))
              else
                Icon(Icons.link_off, color: fg, size: 18),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  switch (c.state) {
                    ConnState.connecting => '正在安全连接 ${c.profile.name}…',
                    ConnState.reconnecting => '连接中断，正在自动重连…${c.error == null ? '' : '（${c.error}）'}',
                    _ => c.error ?? '无法连接',
                  },
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: fg, fontSize: 13),
                ),
              ),
              if (unauthorized)
                TextButton(
                  onPressed: () =>
                      Navigator.of(context)
                          .push(MaterialPageRoute(builder: (_) => WelcomePage(repairFor: c.profile, pushed: true)))
                          .then((_) => c.connect()),
                  child: const Text('重新配对'),
                )
              else
                TextButton(onPressed: c.connect, child: const Text('立即重连')),
            ],
          ),
        ),
      ),
    );
  }
}

/// 页面通用：未连接时的占位。
Widget offlinePlaceholder(BuildContext context) {
  final c = ConnScope.of(context);
  if (c.state == ConnState.unauthorized) {
    return MessageView(icon: Icons.link_off, text: c.error ?? '授权失效，请重新配对');
  }
  return const LoadingView();
}
