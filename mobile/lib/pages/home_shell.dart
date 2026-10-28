import 'package:material_ui/material_ui.dart';

import 'dashboard_page.dart';
import 'logs_page.dart';
import 'robots_page.dart';
import 'tools_page.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _Dest {
  final String label;
  final IconData icon;
  final IconData selectedIcon;

  const _Dest(this.label, this.icon, this.selectedIcon);
}

const _dests = [
  _Dest('仪表盘', Icons.space_dashboard_outlined, Icons.space_dashboard),
  _Dest('机器人', Icons.smart_toy_outlined, Icons.smart_toy),
  _Dest('日志', Icons.receipt_long_outlined, Icons.receipt_long),
  _Dest('工具', Icons.widgets_outlined, Icons.widgets),
];

class _HomeShellState extends State<HomeShell> {
  int index = 0;

  void go(int i) => setState(() => index = i);

  /// 从其它页面跳到日志页并选中目标。
  final logTarget = ValueNotifier<String?>(null);

  @override
  void dispose() {
    logTarget.dispose();
    super.dispose();
  }

  void openLogs(String target) {
    logTarget.value = target;
    go(2);
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.of(context).size.width >= 720;
    final pages = [
      DashboardPage(active: index == 0, onOpenRobots: () => go(1)),
      RobotsPage(active: index == 1, onOpenLogs: openLogs),
      LogsPage(active: index == 2, target: logTarget),
      const ToolsPage(),
    ];
    final body = IndexedStack(index: index, children: pages);
    if (wide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: index,
              onDestinationSelected: go,
              labelType: NavigationRailLabelType.all,
              groupAlignment: -0.85,
              destinations: [
                for (final d in _dests)
                  NavigationRailDestination(
                    icon: Icon(d.icon),
                    selectedIcon: Icon(d.selectedIcon),
                    label: Text(d.label),
                  ),
              ],
            ),
            Expanded(child: body),
          ],
        ),
      );
    }
    return Scaffold(
      body: body,
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: go,
        destinations: [
          for (final d in _dests)
            NavigationDestination(icon: Icon(d.icon), selectedIcon: Icon(d.selectedIcon), label: d.label),
        ],
      ),
    );
  }
}
