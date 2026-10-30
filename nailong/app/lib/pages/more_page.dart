import 'package:material_ui/material_ui.dart';

import '../core/connection.dart';
import '../core/store.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'backup_page.dart';
import 'conn_scope.dart';
import 'sources_page.dart';
import 'welcome_page.dart';

class MorePage extends StatelessWidget {
  const MorePage({super.key});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final conn = ConnScope.of(context);
    Widget item(IconData icon, String title, Widget page, {String? sub}) => ListTile(
      leading: Icon(icon, color: cs.onSurfaceVariant),
      title: Text(title),
      subtitle: sub == null ? null : Text(sub),
      trailing: Icon(Icons.chevron_right, color: cs.outline),
      onTap: () => pushPage(context, page),
    );
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar(pinned: true, title: Text('更多')),
          SliverList.list(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: GestureDetector(
                  onTap: () => pushPage(context, const ServersPage()),
                  child: HeroCard(
                    padding: const EdgeInsets.all(18),
                    child: Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.18),
                            shape: BoxShape.circle,
                          ),
                          child: const AppLogo(size: 44),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                conn.profile.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '${conn.profile.user}@${conn.profile.address}',
                                style: TextStyle(color: Colors.white.withValues(alpha: 0.78), fontSize: 13),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 5),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.2),
                            borderRadius: BorderRadius.circular(99),
                          ),
                          child: Text(
                            conn.state == ConnState.online ? '● 在线' : '○ 离线',
                            style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SectionTitle('管理'),
              GroupCard(
                children: [
                  item(Icons.view_in_ar_outlined, 'Docker 容器', const DockerPage()),
                  item(Icons.archive_outlined, '备份恢复', const BackupPage()),
                  item(Icons.speed, '下载加速', const SourcesPage(), sub: 'GitHub / Docker 镜像 / PyPI'),
                ],
              ),
              const SectionTitle('安全'),
              GroupCard(
                children: [
                  item(Icons.dns_outlined, '服务器管理', const ServersPage(), sub: '添加、切换、重新连接、重新配对'),
                  item(Icons.devices_outlined, '设备授权', const DevicesPage(), sub: '查看、撤销设备，轮换令牌'),
                ],
              ),
              const SectionTitle('应用'),
              GroupCard(
                children: [
                  item(Icons.palette_outlined, '主题', const ThemePage()),
                  ListTile(
                    leading: Icon(Icons.info_outline, color: cs.onSurfaceVariant),
                    title: const Text('关于奶龙'),
                    onTap: () => showAboutDialog(
                      context: context,
                      applicationName: '奶龙',
                      applicationVersion: '1.0.0 · Nailong AstrBot Manager',
                      applicationIcon: const AppLogo(size: 56),
                      children: const [
                        Text('轻松部署与管理你的 AstrBot。\n\n界面风格参考 FlClash；部署基于 AstrBot 与 NapCat 官方 Docker 镜像。'),
                      ],
                    ),
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

// ---------------------------------------------------------------- Docker

class DockerPage extends StatefulWidget {
  const DockerPage({super.key});

  @override
  State<DockerPage> createState() => _DockerPageState();
}

class _DockerPageState extends State<DockerPage> {
  List<Map<String, dynamic>>? rows;
  String? error;
  final busy = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final api = ConnScope.maybeOf(context)?.api;
    if (api == null) return setState(() => error = '未连接服务器');
    try {
      final r = (await api.get('/api/docker/containers') as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      if (mounted) setState(() => rows = r);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _act(String name, String action) async {
    final api = ConnScope.of(context).api!;
    if (action != 'start' &&
        !await confirmDialog(
          context,
          title: '${action == 'stop' ? '停止' : '重启'} $name？',
          destructive: action == 'stop',
        )) {
      return;
    }
    if (!mounted) return;
    setState(() => busy.add(name));
    await runAction(
      context,
      () => api.post('/api/docker/containers/$name/$action', null, const Duration(seconds: 120)),
      success: '操作成功',
    );
    if (mounted) setState(() => busy.remove(name));
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _load,
        child: CustomScrollView(
          slivers: [
            const SliverAppBar(pinned: true, title: Text('Docker 容器')),
            if (rows == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error == null ? const LoadingView() : MessageView(icon: Icons.error_outline, text: error!),
              )
            else
              SliverList.list(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: Text(
                      '只能控制 AstrBot / NapCat；其它容器只读显示，奶龙不会改动。',
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13),
                    ),
                  ),
                  GroupCard(
                    children: [
                      for (final c in rows!)
                        ListTile(
                          leading: Icon(
                            Icons.circle,
                            size: 12,
                            color: c['state'] == 'running' ? cs.success : cs.outline,
                          ),
                          title: Row(
                            children: [
                              Flexible(child: Text(c['name'].toString(), overflow: TextOverflow.ellipsis)),
                              if ((c['role'] ?? '').toString().isNotEmpty) ...[
                                const SizedBox(width: 6),
                                StatusChip(c['role'].toString(), Tone.info, dot: false),
                              ],
                            ],
                          ),
                          subtitle: Text('${c['image']}\n${c['status']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                          isThreeLine: true,
                          trailing: c['controllable'] != true
                              ? null
                              : busy.contains(c['name'])
                              ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                              : PopupMenuButton<String>(
                                  onSelected: (v) => _act(c['name'] as String, v),
                                  itemBuilder: (_) => [
                                    if (c['state'] != 'running') const PopupMenuItem(value: 'start', child: Text('启动')),
                                    const PopupMenuItem(value: 'restart', child: Text('重启')),
                                    if (c['state'] == 'running') const PopupMenuItem(value: 'stop', child: Text('停止')),
                                  ],
                                ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 32),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- 服务器管理

class ServersPage extends StatelessWidget {
  const ServersPage({super.key});

  @override
  Widget build(BuildContext context) {
    final store = StoreScope.of(context);
    final cs = Theme.of(context).colorScheme;
    final conn = ConnScope.maybeOf(context);
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const WelcomePage(pushed: true))),
        icon: const Icon(Icons.add),
        label: const Text('添加服务器'),
      ),
      body: CustomScrollView(
        slivers: [
          const SliverAppBar(pinned: true, title: Text('服务器管理')),
          SliverList.list(
            children: [
              for (final s in store.servers)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                  child: InfoCard(
                    selected: s.id == store.currentId,
                    onTap: () {
                      if (s.id != store.currentId) {
                        store.select(s.id);
                        Navigator.of(context).popUntil((r) => r.isFirst);
                      }
                    },
                    padding: const EdgeInsets.fromLTRB(16, 12, 4, 12),
                    child: Row(
                      children: [
                        Icon(Icons.dns, color: s.id == store.currentId ? cs.onSecondaryContainer : cs.onSurfaceVariant),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(s.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                              Text(
                                '${s.user}@${s.address} · Agent 127.0.0.1:${s.agentPort}',
                                style: TextStyle(fontSize: 12.5, color: cs.onSurfaceVariant),
                              ),
                              Text(
                                s.id == store.currentId && conn != null
                                    ? (conn.state == ConnState.online ? '在线' : '离线 · ${conn.error ?? ''}')
                                    : (s.lastOnline == 0
                                          ? '未连接'
                                          : '上次在线 ${DateTime.fromMillisecondsSinceEpoch(s.lastOnline).toString().substring(0, 16)}'),
                                style: TextStyle(fontSize: 12, color: cs.outline),
                              ),
                            ],
                          ),
                        ),
                        PopupMenuButton<String>(
                          onSelected: (v) async {
                            switch (v) {
                              case 'reconnect':
                                conn?.connect();
                                toast(context, '正在重新连接');
                              case 'repair':
                                await Navigator.of(context)
                                    .push(MaterialPageRoute(builder: (_) => WelcomePage(repairFor: s, pushed: true)));
                                conn?.connect();
                              case 'rename':
                                final c = TextEditingController(text: s.name);
                                final name = await showDialog<String>(
                                  context: context,
                                  builder: (d) => AlertDialog(
                                    title: const Text('重命名'),
                                    content: TextField(controller: c, autofocus: true),
                                    actions: [
                                      TextButton(onPressed: () => Navigator.pop(d), child: const Text('取消')),
                                      FilledButton(onPressed: () => Navigator.pop(d, c.text), child: const Text('保存')),
                                    ],
                                  ),
                                );
                                if (name != null) store.rename(s, name);
                              case 'trust':
                                if (await confirmDialog(
                                  context,
                                  title: '重新信任服务器身份？',
                                  message: '仅在你确认服务器重装过系统、SSH 主机密钥确实变化时使用。之后需要重新配对。',
                                )) {
                                  await store.forgetHost('${s.host.toLowerCase()}:${s.port}');
                                  s.hostKey = '';
                                  if (context.mounted) {
                                    await Navigator.of(
                                      context,
                                    ).push(MaterialPageRoute(builder: (_) => WelcomePage(repairFor: s, pushed: true)));
                                  }
                                }
                              case 'delete':
                                if (await confirmDialog(
                                  context,
                                  title: '删除 ${s.name}？',
                                  message: '只删除本机保存的连接信息和密钥，不会改动服务器。',
                                  destructive: true,
                                  confirmText: '删除',
                                )) {
                                  await store.removeServer(s);
                                  if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
                                }
                            }
                          },
                          itemBuilder: (_) => [
                            if (s.id == store.currentId) const PopupMenuItem(value: 'reconnect', child: Text('重新连接')),
                            const PopupMenuItem(value: 'repair', child: Text('重新配对')),
                            const PopupMenuItem(value: 'rename', child: Text('重命名')),
                            const PopupMenuItem(value: 'trust', child: Text('重新信任主机密钥')),
                            PopupMenuItem(
                              value: 'delete',
                              child: Text('删除', style: TextStyle(color: cs.error)),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 96),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- 设备授权

class DevicesPage extends StatefulWidget {
  const DevicesPage({super.key});

  @override
  State<DevicesPage> createState() => _DevicesPageState();
}

class _DevicesPageState extends State<DevicesPage> {
  Map<String, dynamic>? data;
  String? error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final api = ConnScope.maybeOf(context)?.api;
    if (api == null) return setState(() => error = '未连接服务器');
    try {
      final d = Map<String, dynamic>.from(await api.get('/api/devices') as Map);
      if (mounted) setState(() => data = d);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _revoke(Map<String, dynamic> d) async {
    final isMe = d['id'] == data!['current'];
    if (!await confirmDialog(
      context,
      title: '撤销 ${d['name']} 的授权？',
      message: isMe ? '这是本机！撤销后本机需要重新配对（需要 SSH 密码）。' : '该设备将无法再管理这台服务器。',
      destructive: true,
      confirmText: '撤销',
    )) {
      return;
    }
    if (!mounted) return;
    await runAction(context, () => ConnScope.of(context).api!.delete('/api/devices/${d['id']}'), success: '已撤销');
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final devices = ((data?['devices'] ?? []) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    String date(dynamic s) =>
        s == null ? '-' : DateTime.fromMillisecondsSinceEpoch((s as int) * 1000).toString().substring(0, 16);
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar(pinned: true, title: Text('设备授权')),
          if (data == null)
            SliverFillRemaining(
              hasScrollBody: false,
              child: error == null ? const LoadingView() : MessageView(icon: Icons.error_outline, text: error!),
            )
          else
            SliverList.list(
              children: [
                GroupCard(
                  children: [
                    for (final d in devices)
                      ListTile(
                        leading: Icon(Icons.smartphone, color: d['revoked'] == true ? cs.outline : cs.primary),
                        title: Row(
                          children: [
                            Flexible(child: Text(d['name'].toString())),
                            if (d['id'] == data!['current']) ...[
                              const SizedBox(width: 6),
                              const StatusChip('本机', Tone.info, dot: false),
                            ],
                            if (d['revoked'] == true) ...[
                              const SizedBox(width: 6),
                              const StatusChip('已撤销', Tone.idle, dot: false),
                            ],
                          ],
                        ),
                        subtitle: Text(
                          '配对 ${date(d['created_at'])} · 最近 ${date(d['last_seen'])}\n令牌到期 ${date(d['expires_at'])}',
                        ),
                        isThreeLine: true,
                        trailing: d['revoked'] == true
                            ? null
                            : IconButton(
                                icon: Icon(Icons.block, color: cs.error),
                                onPressed: () => _revoke(d),
                              ),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: FilledButton.tonalIcon(
                    onPressed: () async {
                      await runAction(context, () => ConnScope.of(context).rotateNow(), success: '访问令牌已轮换');
                      _load();
                    },
                    icon: const Icon(Icons.autorenew),
                    label: const Text('立即轮换本机访问令牌'),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: Text(
                    '令牌有效期 30 天，剩余不足 7 天时自动轮换。服务器只保存令牌的哈希。',
                    style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- 主题

const _colors = [
  brandIndigo,
  brandGraphite,
  0xFFFF8D28,
  0xFFFF2D55,
  0xFFCB30E0,
  0xFF5856D6,
  0xFF007AFF,
  0xFF34C759,
  0xFF8E8E93,
];

class ThemePage extends StatelessWidget {
  const ThemePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar(pinned: true, title: Text('主题')),
          SliverList.list(
            children: [
              const SectionTitle('外观'),
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
              const SectionTitle('按钮风格'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: SegmentedButton<ButtonLook>(
                  segments: const [
                    ButtonSegment(value: ButtonLook.light, icon: Icon(Icons.light_mode_outlined), label: Text('浅色渐变')),
                    ButtonSegment(value: ButtonLook.dark, icon: Icon(Icons.dark_mode_outlined), label: Text('黑色渐变')),
                  ],
                  selected: {s.buttonLook},
                  onSelectionChanged: (v) => s.setButtonLook(v.first),
                ),
              ),
              const SectionTitle('主题色'),
              GroupCard(
                children: [
                  SwitchListTile(
                    secondary: const Icon(Icons.wallpaper),
                    title: const Text('动态取色（Material You）'),
                    subtitle: const Text('跟随壁纸配色，Android 12 及以上'),
                    value: s.dynamicColor,
                    onChanged: s.setDynamicColor,
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Wrap(
                  spacing: 14,
                  runSpacing: 14,
                  children: [
                    for (final c in _colors)
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
              const SizedBox(height: 8),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text('第一个是默认的石墨灰。', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
