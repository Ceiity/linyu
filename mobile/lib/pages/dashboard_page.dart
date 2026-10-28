import 'dart:convert';

import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class DashboardPage extends StatefulWidget {
  final bool active;
  final VoidCallback onOpenRobots;

  const DashboardPage({super.key, required this.active, required this.onOpenRobots});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> with WidgetsBindingObserver, PollingMixin {
  Map<String, dynamic>? data;
  String? error;
  final cpuHistory = <double>[];
  final memHistory = <double>[];

  @override
  Duration get pollInterval => const Duration(seconds: 4);

  @override
  bool get pollActive => widget.active;

  @override
  void initState() {
    super.initState();
    initPolling();
  }

  @override
  void didUpdateWidget(DashboardPage old) {
    super.didUpdateWidget(old);
    syncPolling();
  }

  @override
  void dispose() {
    disposePolling();
    super.dispose();
  }

  @override
  Future<void> poll() async {
    final api = AppScope.read(context).api;
    if (api == null) return;
    try {
      final d = await api.get('/api/dashboard');
      if (!mounted) return;
      final m = Map<String, dynamic>.from(d as Map);
      final sys = (m['system'] ?? {}) as Map;
      _push(cpuHistory, _cpuPercent(sys));
      _push(memHistory, ((sys['memory'] ?? {})['used_percent'] ?? 0 as num).toDouble());
      setState(() {
        data = m;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  void _push(List<double> l, double v) {
    l.add(v);
    if (l.length > 30) l.removeAt(0);
  }

  double _load(Map sys) {
    final l = sys['load'];
    return l is List && l.isNotEmpty ? (l.first as num).toDouble() : 0;
  }

  // 与网页面板一致：负载 × 25 估算 CPU 占用
  double _cpuPercent(Map sys) => (_load(sys) * 25).clamp(0, 100).toDouble();

  Future<void> _astrbotActions() async {
    final api = AppScope.read(context).api!;
    final running = data?['astrbot']?['running'] == true;
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: const Text('AstrBot 主服务', style: TextStyle(fontWeight: FontWeight.w700)),
              trailing: StatusChip(
                containerStatusText(data?['astrbot']?['status']),
                containerTone(data?['astrbot']?['status']),
              ),
            ),
            if (!running)
              ListTile(
                leading: const Icon(Icons.play_arrow_rounded),
                title: const Text('启动'),
                onTap: () => Navigator.pop(c, 'start'),
              ),
            ListTile(
              leading: const Icon(Icons.restart_alt_rounded),
              title: const Text('重启'),
              onTap: () => Navigator.pop(c, 'restart'),
            ),
            if (running)
              ListTile(
                leading: Icon(Icons.stop_rounded, color: Theme.of(c).colorScheme.error),
                title: Text('停止', style: TextStyle(color: Theme.of(c).colorScheme.error)),
                onTap: () => Navigator.pop(c, 'stop'),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (action == null || !mounted) return;
    if (action != 'start') {
      final ok = await confirmDialog(
        context,
        title: action == 'stop' ? '确认停止 AstrBot？' : '确认重启 AstrBot？',
        message: action == 'stop' ? '停止后所有机器人将不再回复消息。' : '重启期间机器人会短暂离线。',
        destructive: action == 'stop',
      );
      if (!ok || !mounted) return;
    }
    final r = await runAction(context, () => api.post('/api/astrbot/action', {'action': action}), success: '操作已执行');
    if (r != null) poll();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final d = data;
    return Scaffold(
      floatingActionButton: d == null
          ? null
          : FloatingActionButton.extended(
              onPressed: _astrbotActions,
              icon: Icon(d['astrbot']?['running'] == true ? Icons.bolt_rounded : Icons.power_settings_new_rounded),
              label: Text(d['astrbot']?['running'] == true ? 'AstrBot 运行中' : 'AstrBot 已停止'),
            ),
      body: RefreshIndicator(
        onRefresh: poll,
        child: CustomScrollView(
          slivers: [
            SliverAppBar.large(
              title: const Text('仪表盘'),
              actions: [
                Padding(
                  padding: const EdgeInsets.only(right: 12),
                  child: Chip(avatar: const Icon(Icons.dns, size: 16), label: Text(s.current?.name ?? '')),
                ),
              ],
            ),
            if (d == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error == null
                    ? const LoadingView()
                    : MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: poll),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
                sliver: SliverToBoxAdapter(child: _grid(d)),
              ),
          ],
        ),
      ),
    );
  }

  Widget _grid(Map<String, dynamic> d) {
    final cs = Theme.of(context).colorScheme;
    final sys = Map<String, dynamic>.from(d['system'] ?? {});
    final mem = Map<String, dynamic>.from(sys['memory'] ?? {});
    final disk = Map<String, dynamic>.from(sys['disk'] ?? {});
    final napcats = (d['napcats'] ?? []) as List;
    final runningBots = napcats.where((e) => e['running'] == true).length;
    final astr = Map<String, dynamic>.from(d['astrbot'] ?? {});

    return LayoutBuilder(
      builder: (context, c) {
        const gap = 12.0;
        final cols = c.maxWidth >= 900 ? 4 : (c.maxWidth >= 560 ? 3 : 2);
        final unit = (c.maxWidth - gap * (cols - 1)) / cols;
        double span(int n) => unit * n + gap * (n - 1);
        final wide = cols >= 3 ? span(cols >= 4 ? 2 : 3) : span(2);

        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            if (d['deployed'] != true)
              SizedBox(
                width: span(cols),
                child: _DeployWizard(onDone: poll),
              ),
            SizedBox(
              width: unit,
              child: _Kpi(
                icon: Icons.smart_toy_outlined,
                title: 'AstrBot',
                value: containerStatusText(astr['status']),
                tone: containerTone(astr['status']),
                onTap: _astrbotActions,
              ),
            ),
            SizedBox(
              width: unit,
              child: _Kpi(
                icon: Icons.hub_outlined,
                title: '机器人',
                value: '$runningBots / ${napcats.length}',
                sub: '运行中 / 总数',
                onTap: widget.onOpenRobots,
              ),
            ),
            SizedBox(
              width: unit,
              child: _Kpi(
                icon: Icons.view_in_ar_outlined,
                title: 'Docker',
                value: d['docker']?['ok'] == true ? '正常' : '异常',
                tone: d['docker']?['ok'] == true ? Tone.ok : Tone.bad,
              ),
            ),
            SizedBox(
              width: unit,
              child: _Kpi(
                icon: Icons.speed_outlined,
                title: '系统负载',
                value: _load(sys).toStringAsFixed(2),
                sub: '1 分钟平均',
              ),
            ),
            SizedBox(
              width: wide,
              child: InfoCard(
                icon: Icons.show_chart,
                title: '资源趋势',
                actions: [
                  _Legend(color: cs.primary, text: '内存'),
                  const SizedBox(width: 10),
                  _Legend(color: cs.tertiary, text: 'CPU'),
                ],
                child: SparkLine(values: memHistory, values2: cpuHistory),
              ),
            ),
            SizedBox(
              width: wide,
              child: InfoCard(
                icon: Icons.memory,
                title: '资源占用',
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        RingGauge(percent: _cpuPercent(sys), label: 'CPU'),
                        RingGauge(percent: (mem['used_percent'] ?? 0 as num).toDouble(), label: '内存'),
                        RingGauge(percent: (disk['used_percent'] ?? 0 as num).toDouble(), label: '磁盘'),
                      ],
                    ),
                    const SizedBox(height: 14),
                    _kv(
                      '内存',
                      '${fmtBytes(((mem['total'] ?? 0) as num) - ((mem['available'] ?? 0) as num))} / ${fmtBytes(mem['total'] as num?)}',
                    ),
                    _kv('磁盘', '${fmtBytes(disk['used'] as num?)} / ${fmtBytes(disk['total'] as num?)}'),
                  ],
                ),
              ),
            ),
            SizedBox(
              width: wide,
              child: InfoCard(
                icon: Icons.lan_outlined,
                title: '网络',
                child: Column(
                  children: [
                    _kv('公网 IP', d['public_ip']?.toString() ?? '-', copy: true),
                    _kv('内网 IP', d['private_ip']?.toString() ?? '-', copy: true),
                    _kv('Docker 网络', d['network']?.toString() ?? '-'),
                  ],
                ),
              ),
            ),
            SizedBox(
              width: wide,
              child: InfoCard(
                icon: Icons.history,
                title: '最近操作',
                child: _RecentList(lines: ((d['recent'] ?? []) as List).map((e) => e.toString()).toList()),
              ),
            ),
            SizedBox(
              width: span(cols),
              child: InfoCard(
                icon: Icons.inventory_2_outlined,
                title: '容器',
                child: _Containers(raw: d['docker']?['containers']?.toString() ?? ''),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _kv(String k, String v, {bool copy = false}) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: copy ? () => copyText(context, v, label: k) : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            Text(k, style: TextStyle(color: cs.onSurfaceVariant)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                v,
                textAlign: TextAlign.right,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
            if (copy) ...[const SizedBox(width: 6), Icon(Icons.copy_rounded, size: 14, color: cs.outline)],
          ],
        ),
      ),
    );
  }
}

class _Kpi extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;
  final String? sub;
  final Tone? tone;
  final VoidCallback? onTap;

  const _Kpi({required this.icon, required this.title, required this.value, this.sub, this.tone, this.onTap});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final color = tone == null ? cs.onSurface : toneColor(cs, tone!);
    return InfoCard(
      icon: icon,
      title: title,
      onTap: onTap,
      child: SizedBox(
        height: 52,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                value,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800, color: color),
              ),
            ),
            Text(sub ?? ' ', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  final Color color;
  final String text;

  const _Legend({required this.color, required this.text});

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 4),
      Text(text, style: Theme.of(context).textTheme.labelSmall),
    ],
  );
}

const _actionNames = {
  'login': '登录面板',
  'login.failed': '登录失败',
  'login.rate_limited': '登录被限流',
  'login.crypto_failed': '登录解密失败',
  'settings.save': '保存设置',
  'password_changed': '修改密码',
  'sessions_revoked': '注销所有会话',
  'logout_all_devices': '所有设备退出',
  'astrbot.start': '启动 AstrBot',
  'astrbot.stop': '停止 AstrBot',
  'astrbot.restart': '重启 AstrBot',
  'astrbot.no_prefix': '应用免 @ 配置',
  'connection.repair': '一键配置连接',
  'napcat.add': '新增机器人',
  'napcat.delete': '删除机器人',
  'napcat.start': '启动机器人',
  'napcat.stop': '停止机器人',
  'napcat.restart': '重启机器人',
  'napcat.restart_all': '重启全部机器人',
  'napcat.cleanup_idle': '清理空闲机器人',
  'napcat.qq.qrcode': '获取登录二维码',
  'napcat.qq.refresh': '刷新登录二维码',
  'napcat.qq.status': '查询登录状态',
  'napcat.qq.already_login': '机器人已登录',
  'napcat.open': '打开 NapCat WebUI',
  'deploy.start': '初始化部署',
  'backup': '创建备份',
  'backup.restore': '恢复备份',
  'update.astrbot': '更新 AstrBot',
  'update.napcat': '更新机器人',
  'update.all': '全部更新',
  'https.setup': '配置 HTTPS',
  'device.report': '设备上报',
};

String _actionText(String a) => _actionNames[a] ?? a;

class _RecentList extends StatelessWidget {
  final List<String> lines;

  const _RecentList({required this.lines});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (lines.isEmpty) return Text('暂无操作', style: TextStyle(color: cs.onSurfaceVariant));
    final items = lines.reversed.take(6).map((l) {
      // 审计日志每行一个 JSON：{time, user, action, ok, detail}
      var ok = true;
      var title = l;
      var time = '';
      try {
        final j = jsonDecode(l);
        if (j is Map) {
          ok = j['ok'] != false;
          title = _actionText(j['action']?.toString() ?? '');
          time = (j['time'] ?? '').toString();
        }
      } catch (_) {}
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(color: ok ? cs.success : cs.error, shape: BoxShape.circle),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13, height: 1.4),
              ),
            ),
            if (time.isNotEmpty)
              Text(
                time.length > 19 ? time.substring(5, 19) : time,
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
          ],
        ),
      );
    });
    return Column(children: items.toList());
  }
}

class _Containers extends StatelessWidget {
  final String raw;

  const _Containers({required this.raw});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final rows = raw.split('\n').where((l) => l.trim().isNotEmpty).map((l) => l.split('\t')).toList();
    if (rows.isEmpty) return Text('暂无容器', style: TextStyle(color: cs.onSurfaceVariant));
    return Column(
      children: [
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                Icon(Icons.circle, size: 8, color: (r.length > 2 && r[2].startsWith('Up')) ? cs.success : cs.outline),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        botName(r[0]) == r[0] ? r[0] : '${botName(r[0])} · ${r[0]}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      if (r.length > 1)
                        Text(
                          r[1],
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                        ),
                    ],
                  ),
                ),
                if (r.length > 2)
                  Flexible(
                    child: Text(
                      r[2],
                      textAlign: TextAlign.right,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
                    ),
                  ),
              ],
            ),
          ),
      ],
    );
  }
}

class _DeployWizard extends StatefulWidget {
  final Future<void> Function() onDone;

  const _DeployWizard({required this.onDone});

  @override
  State<_DeployWizard> createState() => _DeployWizardState();
}

class _DeployWizardState extends State<_DeployWizard> {
  final count = TextEditingController(text: '1');
  final token = TextEditingController(text: 'yuyu521521');

  @override
  void dispose() {
    count.dispose();
    token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final api = AppScope.read(context).api!;
    return InfoCard(
      icon: Icons.rocket_launch_outlined,
      title: '初始化部署',
      selected: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('尚未检测到 AstrBot。填写机器人数量和连接 Token，一键部署 AstrBot + NapCat。'),
          const SizedBox(height: 12),
          Row(
            children: [
              SizedBox(
                width: 110,
                child: TextField(
                  controller: count,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '机器人数量'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: token,
                  decoration: const InputDecoration(labelText: '连接 Token'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            icon: const Icon(Icons.play_arrow_rounded),
            label: const Text('开始自动部署'),
            onPressed: () async {
              final n = int.tryParse(count.text.trim());
              if (n == null || n < 0 || n > 999) return toast(context, '数量必须是 0-999');
              await startTask(context, api, '/api/deploy/start', {
                'napcat_count': n,
                'reverse_token': token.text.trim(),
              });
              widget.onDone();
            },
          ),
        ],
      ),
    );
  }
}
