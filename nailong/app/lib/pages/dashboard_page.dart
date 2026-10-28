import 'package:material_ui/material_ui.dart';

import '../core/connection.dart';
import '../ui/widgets.dart';
import 'backup_page.dart';
import 'conn_scope.dart';
import 'home_shell.dart';

class DashboardPage extends StatefulWidget {
  final bool active;
  final void Function(String target) onOpenLogs;
  final void Function(int tab) onGo;

  const DashboardPage({super.key, required this.active, required this.onOpenLogs, required this.onGo});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> with WidgetsBindingObserver, PollingMixin {
  Map<String, dynamic>? data;
  String? error;
  final rx = <double>[];
  final tx = <double>[];
  final busy = <String>{};

  @override
  Duration get pollInterval => const Duration(seconds: 3);

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
    final api = ConnScope.maybeOf(context)?.api;
    if (api == null) return;
    try {
      final d = Map<String, dynamic>.from(await api.get('/api/overview') as Map);
      final m = Map<String, dynamic>.from(d['metrics'] as Map);
      _push(rx, (m['net_rx_bps'] as num).toDouble());
      _push(tx, (m['net_tx_bps'] as num).toDouble());
      if (mounted) {
        setState(() {
          data = d;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  void _push(List<double> l, double v) {
    l.add(v);
    if (l.length > 30) l.removeAt(0);
  }

  Future<void> _service(String role, String action) async {
    final api = ConnScope.of(context).api;
    if (api == null) return;
    if (action != 'start') {
      final ok = await confirmDialog(
        context,
        title: '${action == 'stop' ? '停止' : '重启'}${role == 'astrbot' ? ' AstrBot' : ' NapCat'}？',
        message: action == 'stop' ? '停止后机器人将不再回复消息。' : '重启期间机器人会短暂离线。',
        confirmText: action == 'stop' ? '停止' : '重启',
        destructive: action == 'stop',
      );
      if (!ok || !mounted) return;
    }
    setState(() => busy.add('$role.$action'));
    await runAction(
      context,
      () => api.post('/api/services/$role/$action', null, const Duration(seconds: 120)),
      success: '操作成功',
    );
    if (mounted) setState(() => busy.remove('$role.$action'));
    poll();
  }

  @override
  Widget build(BuildContext context) {
    final conn = ConnScope.of(context);
    final d = data;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: poll,
        child: CustomScrollView(
          slivers: [
            SliverAppBar.large(
              title: Row(
                children: [
                  const AppLogo(size: 34),
                  const SizedBox(width: 10),
                  Flexible(child: Text(conn.profile.name, overflow: TextOverflow.ellipsis)),
                ],
              ),
            ),
            if (d == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: conn.state == ConnState.online && error != null
                    ? MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: poll)
                    : offlinePlaceholder(context),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
                sliver: SliverToBoxAdapter(child: _body(d, conn)),
              ),
          ],
        ),
      ),
    );
  }

  Widget _body(Map<String, dynamic> d, ServerConnection conn) {
    final cs = Theme.of(context).colorScheme;
    final m = Map<String, dynamic>.from(d['metrics'] as Map);
    final astr = d['astrbot'] == null ? null : Map<String, dynamic>.from(d['astrbot'] as Map);
    final naps = ((d['napcat'] ?? []) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    final docker = Map<String, dynamic>.from(d['docker'] as Map);
    final napRunning = naps.where((n) => n['running'] == true).length;
    final online = conn.state == ConnState.online;
    final maxNet = [...rx, ...tx, 64 * 1024.0].reduce((a, b) => a > b ? a : b) * 1.2;

    return LayoutBuilder(
      builder: (context, c) {
        const gap = 12.0;
        final cols = c.maxWidth >= 560 ? 4 : 2;
        final unit = (c.maxWidth - gap * (cols - 1)) / cols;
        final full = c.maxWidth;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            SizedBox(
              width: unit,
              child: _StatusCard(
                icon: Icons.smart_toy_outlined,
                title: 'AstrBot',
                value: astr == null ? '未接管' : containerStatusText(astr['state']?.toString()),
                tone: astr == null ? Tone.idle : containerTone(astr['state']?.toString()),
              ),
            ),
            SizedBox(
              width: unit,
              child: _StatusCard(
                icon: Icons.chat_bubble_outline,
                title: 'NapCat',
                value: naps.isEmpty ? '未接管' : '$napRunning / ${naps.length} 运行',
                tone: naps.isEmpty ? Tone.idle : (napRunning == naps.length ? Tone.ok : Tone.warn),
                onTap: () => widget.onGo(1),
              ),
            ),
            SizedBox(
              width: unit,
              child: _StatusCard(
                icon: Icons.view_in_ar_outlined,
                title: 'Docker',
                value: docker['ok'] == true ? '正常' : '异常',
                sub: docker['version']?.toString(),
                tone: docker['ok'] == true ? Tone.ok : Tone.bad,
              ),
            ),
            SizedBox(
              width: unit,
              child: _StatusCard(
                icon: Icons.dns_outlined,
                title: '服务器',
                value: online ? '在线' : '离线',
                sub: '运行 ${fmtDuration((m['uptime'] as num?)?.toInt() ?? 0)}',
                tone: online ? Tone.ok : Tone.bad,
              ),
            ),
            SizedBox(
              width: full,
              child: InfoCard(
                icon: Icons.memory,
                title: '资源占用',
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        RingGauge(
                          percent: (m['cpu_percent'] as num?)?.toDouble() ?? 0,
                          label: 'CPU ${m['cpu_cores']} 核',
                        ),
                        RingGauge(percent: (m['mem_percent'] as num?)?.toDouble() ?? 0, label: '内存'),
                        RingGauge(percent: (m['disk_percent'] as num?)?.toDouble() ?? 0, label: '磁盘'),
                      ],
                    ),
                    const SizedBox(height: 12),
                    _kv('内存', '${fmtBytes(m['mem_used'] as num?)} / ${fmtBytes(m['mem_total'] as num?)}'),
                    _kv('磁盘', '${fmtBytes(m['disk_used'] as num?)} / ${fmtBytes(m['disk_total'] as num?)}'),
                    _kv('负载', ((m['load'] ?? []) as List).map((e) => (e as num).toStringAsFixed(2)).join('  ')),
                  ],
                ),
              ),
            ),
            SizedBox(
              width: full,
              child: InfoCard(
                icon: Icons.swap_vert,
                title: '网络',
                actions: [
                  _Legend(color: cs.primary, text: '↓ ${fmtSpeed(m['net_rx_bps'] as num?)}'),
                  const SizedBox(width: 12),
                  _Legend(color: cs.tertiary, text: '↑ ${fmtSpeed(m['net_tx_bps'] as num?)}'),
                ],
                child: SparkLine(values: rx, values2: tx, maxValue: maxNet),
              ),
            ),
            SizedBox(
              width: full,
              child: InfoCard(
                icon: Icons.bolt_outlined,
                title: '快捷操作',
                child: Column(
                  children: [
                    Row(
                      children: [
                        _QuickAction(
                          icon: Icons.play_arrow_rounded,
                          label: '启动',
                          busy: busy.contains('astrbot.start'),
                          onTap: astr == null || astr['running'] == true ? null : () => _service('astrbot', 'start'),
                        ),
                        _QuickAction(
                          icon: Icons.stop_rounded,
                          label: '停止',
                          busy: busy.contains('astrbot.stop'),
                          onTap: astr?['running'] == true ? () => _service('astrbot', 'stop') : null,
                        ),
                        _QuickAction(
                          icon: Icons.restart_alt_rounded,
                          label: '重启',
                          busy: busy.contains('astrbot.restart'),
                          onTap: astr == null ? null : () => _service('astrbot', 'restart'),
                        ),
                        _QuickAction(
                          icon: Icons.receipt_long_outlined,
                          label: '日志',
                          onTap: () => widget.onOpenLogs('astrbot'),
                        ),
                        _QuickAction(
                          icon: Icons.backup_outlined,
                          label: '备份',
                          onTap: () => pushPage(context, const BackupPage()),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text('启动 / 停止 / 重启作用于 AstrBot', style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
                  ],
                ),
              ),
            ),
            SizedBox(
              width: full,
              child: InfoCard(
                icon: Icons.info_outline,
                title: '服务器信息',
                child: Column(
                  children: [
                    _kv('地址', conn.profile.address),
                    _kv('系统', '${d['server']?['os'] ?? '-'} · ${d['server']?['arch'] ?? ''}'),
                    _kv('主机名', '${d['server']?['hostname'] ?? d['hostname']}'),
                    _kv('Agent', 'v${d['agent_version']} · 127.0.0.1:${conn.profile.agentPort}（SSH 隧道）'),
                    if (astr != null) _kv('AstrBot 镜像', '${astr['image']}'),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _kv(String k, String v) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(k, style: TextStyle(color: cs.onSurfaceVariant)),
          ),
          Expanded(
            child: Text(
              v,
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;
  final String? sub;
  final Tone tone;
  final VoidCallback? onTap;

  const _StatusCard({
    required this.icon,
    required this.title,
    required this.value,
    required this.tone,
    this.sub,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return InfoCard(
      icon: icon,
      title: title,
      onTap: onTap,
      child: SizedBox(
        height: 50,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(color: toneColor(cs, tone), shape: BoxShape.circle),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      value,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                    ),
                  ),
                ),
              ],
            ),
            Text(
              sub ?? ' ',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final bool busy;

  const _QuickAction({required this.icon, required this.label, this.onTap, this.busy = false});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final enabled = onTap != null && !busy;
    return Expanded(
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: enabled ? onTap : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Column(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: enabled ? cs.secondaryContainer : cs.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: busy
                    ? const Padding(padding: EdgeInsets.all(14), child: CircularProgressIndicator(strokeWidth: 2.5))
                    : Icon(icon, color: enabled ? cs.onSecondaryContainer : cs.outline),
              ),
              const SizedBox(height: 6),
              Text(label, style: TextStyle(fontSize: 12.5, color: enabled ? cs.onSurface : cs.outline)),
            ],
          ),
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
