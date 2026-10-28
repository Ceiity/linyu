import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../ui/widgets.dart';
import 'manage_pages.dart';
import 'server_page.dart';
import 'settings_pages.dart';

class ToolsPage extends StatelessWidget {
  const ToolsPage({super.key});

  void _push(BuildContext context, Widget page) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => page));

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    Widget item(IconData icon, String title, {String? sub, VoidCallback? onTap, Color? color}) => ListTile(
      leading: Icon(icon, color: color ?? cs.onSurfaceVariant),
      title: Text(title, style: color == null ? null : TextStyle(color: color)),
      subtitle: sub == null ? null : Text(sub),
      trailing: color == null ? Icon(Icons.chevron_right, color: cs.outline) : null,
      onTap: onTap,
    );
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('工具')),
          SliverList.list(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: InfoCard(
                  child: Row(
                    children: [
                      const AppLogo(size: 48),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              s.current?.name ?? '',
                              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                            ),
                            const SizedBox(height: 2),
                            Text(s.current?.baseUrl ?? '', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
                          ],
                        ),
                      ),
                      if ((s.current?.version ?? '').isNotEmpty)
                        StatusChip('v${s.current!.version}', Tone.info, dot: false),
                    ],
                  ),
                ),
              ),
              const SectionTitle('管理'),
              GroupCard(
                children: [
                  item(
                    Icons.smart_toy_outlined,
                    'AstrBot',
                    sub: '主服务、账号、免 @ 配置',
                    onTap: () => _push(context, const AstrbotPage()),
                  ),
                  item(Icons.task_alt, '任务记录', onTap: () => _push(context, const TasksPage())),
                  item(Icons.archive_outlined, '备份恢复', onTap: () => _push(context, const BackupPage())),
                  item(Icons.system_update_alt, '更新中心', onTap: () => _push(context, const UpdatePage())),
                ],
              ),
              const SectionTitle('设置'),
              GroupCard(
                children: [
                  item(
                    Icons.tune,
                    '面板设置',
                    sub: '掉线守护、QQ 远程登录、危险操作',
                    onTap: () => _push(context, const PanelSettingsPage()),
                  ),
                  item(Icons.shield_outlined, '账号安全', onTap: () => _push(context, const AccountPage())),
                  item(Icons.palette_outlined, '主题', onTap: () => _push(context, const ThemePage())),
                ],
              ),
              const SectionTitle('其它'),
              GroupCard(
                children: [
                  item(Icons.swap_horiz, '切换服务器', onTap: s.leaveServer),
                  item(
                    Icons.info_outline,
                    '关于',
                    onTap: () => showAboutDialog(
                      context: context,
                      applicationName: '淋雨',
                      applicationVersion: '1.0.0',
                      applicationIcon: const AppLogo(size: 48),
                      children: const [Text('AstrBot-Deploy 面板手机客户端。\n界面风格参考 FlClash。')],
                    ),
                  ),
                  item(
                    Icons.logout,
                    '退出登录',
                    color: cs.error,
                    onTap: () async {
                      if (await confirmDialog(context, title: '退出登录？', destructive: true, confirmText: '退出')) {
                        s.logout();
                      }
                    },
                  ),
                ],
              ),
              const SizedBox(height: 32),
            ],
          ),
        ],
      ),
    );
  }
}

class ThemePage extends StatelessWidget {
  const ThemePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('主题')),
          SliverList.list(
            children: [
              const SectionTitle('外观模式'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: SegmentedButton<ThemeMode>(
                  segments: const [
                    ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.brightness_auto), label: Text('跟随系统')),
                    ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode), label: Text('浅色')),
                    ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode), label: Text('深色')),
                  ],
                  selected: {s.themeMode},
                  onSelectionChanged: (v) => s.setThemeMode(v.first),
                ),
              ),
              const SectionTitle('主题色'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Wrap(
                  spacing: 14,
                  runSpacing: 14,
                  children: [
                    for (final c in presetColors)
                      GestureDetector(
                        onTap: () => s.setSeedColor(c),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 200),
                          width: 48,
                          height: 48,
                          decoration: BoxDecoration(
                            color: Color(c),
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: !s.dynamicColor && s.seedColor == c ? cs.onSurface : Colors.transparent,
                              width: 3,
                            ),
                          ),
                          child: !s.dynamicColor && s.seedColor == c
                              ? const Icon(Icons.check, color: Colors.white)
                              : null,
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              GroupCard(
                children: [
                  SwitchListTile(
                    secondary: const Icon(Icons.wallpaper),
                    title: const Text('跟随壁纸取色'),
                    subtitle: const Text('Android 12 及以上'),
                    value: s.dynamicColor,
                    onChanged: s.setDynamicColor,
                  ),
                  SwitchListTile(
                    secondary: const Icon(Icons.contrast),
                    title: const Text('纯黑模式'),
                    subtitle: const Text('深色模式下使用纯黑背景'),
                    value: s.pureBlack,
                    onChanged: s.setPureBlack,
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}
