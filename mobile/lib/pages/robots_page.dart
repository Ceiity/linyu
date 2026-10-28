import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../ui/widgets.dart';

class RobotsPage extends StatefulWidget {
  final bool active;
  final void Function(String target) onOpenLogs;

  const RobotsPage({super.key, required this.active, required this.onOpenLogs});

  @override
  State<RobotsPage> createState() => _RobotsPageState();
}

const _filters = [
  ('all', '全部'),
  ('online', '已登录'),
  ('idle', '空闲'),
  ('assigned', '待扫码'),
  ('abnormal', '需处理'),
  ('stopped', '已停止'),
];

Tone poolTone(String? s) => switch (s) {
  'online' => Tone.ok,
  'idle' => Tone.info,
  'assigned' => Tone.warn,
  'stopped' => Tone.idle,
  _ => Tone.bad,
};

class _RobotsPageState extends State<RobotsPage> with WidgetsBindingObserver, PollingMixin {
  Map<String, dynamic>? data;
  String? error;
  String filter = 'all';
  final pending = <String, String>{};

  @override
  Duration get pollInterval => const Duration(seconds: 5);

  @override
  bool get pollActive => widget.active;

  @override
  void initState() {
    super.initState();
    initPolling();
  }

  @override
  void didUpdateWidget(RobotsPage old) {
    super.didUpdateWidget(old);
    syncPolling();
  }

  @override
  void dispose() {
    disposePolling();
    super.dispose();
  }

  ApiClient get api => AppScope.read(context).api!;

  @override
  Future<void> poll() async {
    try {
      final d = await api.get('/api/napcat/pool', timeout: const Duration(seconds: 40));
      if (!mounted) return;
      setState(() {
        data = Map<String, dynamic>.from(d as Map);
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  List<Map<String, dynamic>> get items =>
      ((data?['items'] ?? []) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();

  Future<void> _add() async {
    final ctrl = TextEditingController(text: '1');
    final n = await showDialog<int>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('新增机器人'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: '数量（1-999）'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(c, int.tryParse(ctrl.text.trim())), child: const Text('创建')),
        ],
      ),
    );
    if (n == null || !mounted) return;
    if (n < 1 || n > 999) return toast(context, '数量必须是 1-999');
    await startTask(context, api, '/api/napcat/action', {'action': 'add', 'count': n});
    poll();
  }

  Future<void> _menu(String v) async {
    switch (v) {
      case 'restart_all':
        if (!await confirmDialog(context, title: '重启全部机器人？', message: '所有机器人会短暂离线。')) return;
        if (!mounted) return;
        await runAction(
          context,
          () => api.post('/api/napcat/action', {'action': 'restart_all'}, const Duration(seconds: 320)),
          success: '已全部重启',
        );
      case 'cleanup':
        if (!await typeConfirmDialog(context, title: '清理空闲机器人', message: '删除所有空闲机器人容器，默认保留数据目录。', word: '清理空闲机器人')) {
          return;
        }
        if (!mounted) return;
        await startTask(context, api, '/api/napcat/pool/cleanup', {'confirm': '清理空闲机器人', 'keep_data': true});
      case 'repair':
        await startTask(context, api, '/api/connection/repair');
    }
    poll();
  }

  Future<void> _act(Map<String, dynamic> r, String action) async {
    final name = r['name'].toString();
    if (action == 'stop' || action == 'restart') {
      final ok = await confirmDialog(
        context,
        title: action == 'stop' ? '停止${botName(name)}？' : '重启${botName(name)}？',
        message: action == 'stop' ? '停止后该机器人将不再响应。' : '重启期间机器人可能暂时离线。',
        destructive: action == 'stop',
      );
      if (!ok) return;
    }
    if (action == 'delete') {
      if (!mounted) return;
      final ok = await typeConfirmDialog(
        context,
        title: '删除${botName(name)}',
        message: '删除容器和索引记录，默认保留数据目录。',
        word: name,
      );
      if (!ok) return;
    }
    if (!mounted) return;
    setState(() => pending[name] = action);
    try {
      if (action == 'delete') {
        await startTask(context, api, '/api/napcat/action', {
          'action': 'delete',
          'name': name,
          'confirm': name,
          'keep_data': true,
        });
      } else {
        await runAction(
          context,
          () => api.post('/api/napcat/action', {'action': action, 'name': name}, const Duration(seconds: 130)),
          success: '操作已执行',
        );
      }
      await poll();
    } finally {
      if (mounted) setState(() => pending.remove(name));
    }
  }

  void _detail(Map<String, dynamic> r) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (c) => _RobotSheet(
        robot: r,
        onAction: (a) {
          Navigator.pop(c);
          if (a == 'qr') {
            showQrLogin(context, api, r['name'].toString()).then((_) => poll());
          } else if (a == 'logs') {
            widget.onOpenLogs(r['name'].toString());
          } else {
            _act(r, a);
          }
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final summary = Map<String, dynamic>.from(data?['summary'] ?? {});
    final list = items.where((e) => filter == 'all' || e['pool_state'] == filter).toList();
    return Scaffold(
      floatingActionButton: FloatingActionButton(onPressed: _add, tooltip: '新增机器人', child: const Icon(Icons.add)),
      body: RefreshIndicator(
        onRefresh: poll,
        child: CustomScrollView(
          slivers: [
            SliverAppBar.large(
              title: const Text('机器人'),
              actions: [
                PopupMenuButton<String>(
                  onSelected: _menu,
                  itemBuilder: (_) => const [
                    PopupMenuItem(
                      value: 'repair',
                      child: ListTile(leading: Icon(Icons.auto_fix_high), title: Text('一键配置连接')),
                    ),
                    PopupMenuItem(
                      value: 'restart_all',
                      child: ListTile(leading: Icon(Icons.restart_alt), title: Text('重启全部')),
                    ),
                    PopupMenuItem(
                      value: 'cleanup',
                      child: ListTile(leading: Icon(Icons.cleaning_services_outlined), title: Text('清理空闲')),
                    ),
                  ],
                ),
              ],
            ),
            SliverToBoxAdapter(
              child: SizedBox(
                height: 48,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  children: [
                    for (final f in _filters)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: FilterChip(
                          selected: filter == f.$1,
                          showCheckmark: false,
                          label: Text('${f.$2} ${f.$1 == 'all' ? (summary['total'] ?? 0) : (summary[f.$1] ?? 0)}'),
                          onSelected: (_) => setState(() => filter = f.$1),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            if (data == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error == null
                    ? const LoadingView()
                    : MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: poll),
              )
            else if (list.isEmpty)
              SliverFillRemaining(
                hasScrollBody: false,
                child: MessageView(
                  icon: Icons.smart_toy_outlined,
                  text: items.isEmpty ? '还没有机器人' : '没有符合条件的机器人',
                  actionText: items.isEmpty ? '新增机器人' : null,
                  onAction: _add,
                ),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                sliver: SliverGrid(
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                    maxCrossAxisExtent: 260,
                    mainAxisSpacing: 12,
                    crossAxisSpacing: 12,
                    mainAxisExtent: 132,
                  ),
                  delegate: SliverChildBuilderDelegate(
                    (_, i) =>
                        _RobotCard(robot: list[i], pending: pending[list[i]['name']], onTap: () => _detail(list[i])),
                    childCount: list.length,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _RobotCard extends StatelessWidget {
  final Map<String, dynamic> robot;
  final String? pending;
  final VoidCallback onTap;

  const _RobotCard({required this.robot, required this.onTap, this.pending});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final state = robot['pool_state']?.toString();
    final nick = robot['login_name']?.toString() ?? '';
    final uin = robot['login_uin']?.toString() ?? '';
    return InfoCard(
      onTap: onTap,
      selected: state == 'online',
      padding: const EdgeInsets.all(14),
      child: SizedBox(
        height: 104,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 16,
                  backgroundColor: toneColor(cs, poolTone(state)).withValues(alpha: 0.16),
                  child: Icon(Icons.smart_toy, size: 18, color: toneColor(cs, poolTone(state))),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    robot['display_name']?.toString() ?? botName(robot['name']),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                if (pending != null)
                  const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
              ],
            ),
            const Spacer(),
            Text(
              nick.isNotEmpty ? nick : (uin.isNotEmpty ? uin : '未登录 QQ'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: tt.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
            Text(
              uin.isNotEmpty && nick.isNotEmpty ? uin : (robot['name']?.toString() ?? ''),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
            ),
            const SizedBox(height: 8),
            StatusChip(robot['pool_state_text']?.toString() ?? '未知', poolTone(state)),
          ],
        ),
      ),
    );
  }
}

class _RobotSheet extends StatelessWidget {
  final Map<String, dynamic> robot;
  final void Function(String action) onAction;

  const _RobotSheet({required this.robot, required this.onAction});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final running = robot['running'] == true;
    final recovery = Map<String, dynamic>.from(robot['recovery'] ?? {});
    Widget kv(String k, String? v) => (v == null || v.isEmpty)
        ? const SizedBox.shrink()
        : InkWell(
            onTap: () => copyText(context, v, label: k),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 9),
              child: Row(
                children: [
                  SizedBox(
                    width: 92,
                    child: Text(k, style: TextStyle(color: cs.onSurfaceVariant)),
                  ),
                  Expanded(
                    child: Text(v, style: const TextStyle(fontWeight: FontWeight.w600)),
                  ),
                ],
              ),
            ),
          );
    return SingleChildScrollView(
      padding: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    robot['display_name']?.toString() ?? botName(robot['name']),
                    style: tt.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
                  ),
                ),
                StatusChip(robot['pool_state_text']?.toString() ?? '', poolTone(robot['pool_state']?.toString())),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
              onPressed: running ? () => onAction('qr') : null,
              icon: const Icon(Icons.qr_code_2),
              label: Text(robot['pool_state'] == 'online' ? '查看登录状态' : '扫码登录 QQ'),
            ),
          ),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Expanded(
                  child: _SheetAction(
                    icon: running ? Icons.stop_rounded : Icons.play_arrow_rounded,
                    label: running ? '停止' : '启动',
                    onTap: () => onAction(running ? 'stop' : 'start'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _SheetAction(icon: Icons.restart_alt_rounded, label: '重启', onTap: () => onAction('restart')),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _SheetAction(icon: Icons.receipt_long_outlined, label: '日志', onTap: () => onAction('logs')),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _SheetAction(
                    icon: Icons.delete_outline,
                    label: '删除',
                    danger: true,
                    onTap: () => onAction('delete'),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          kv('容器', '${robot['name']} · ${containerStatusText(robot['status']?.toString())}'),
          kv('QQ 昵称', robot['login_name']?.toString()),
          kv('QQ 号', robot['login_uin']?.toString()),
          kv('OneBot', robot['onebot_ok'] == true ? '已连接' : '未连接'),
          kv('WebUI 端口', robot['webui_port']?.toString()),
          kv('WS 端口', robot['ws_port']?.toString()),
          kv('HTTP 端口', robot['http_port']?.toString()),
          kv('分配给', robot['assigned_to']?.toString()),
          kv('守护状态', recovery['health']?.toString()),
          kv('目录', robot['directory']?.toString()),
          if (robot['error'] != null) kv('错误', robot['error'].toString()),
        ],
      ),
    );
  }
}

class _SheetAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool danger;

  const _SheetAction({required this.icon, required this.label, required this.onTap, this.danger = false});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final c = danger ? cs.error : cs.onSurface;
    return Material(
      color: danger ? cs.errorContainer.withValues(alpha: 0.5) : cs.surfaceContainerHigh,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14),
          child: Column(
            children: [
              Icon(icon, color: c),
              const SizedBox(height: 6),
              Text(
                label,
                style: TextStyle(color: c, fontSize: 13, fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------- 扫码登录 ----------

Future<void> showQrLogin(BuildContext context, ApiClient api, String name) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => _QrSheet(api: api, name: name),
  );
}

class _QrSheet extends StatefulWidget {
  final ApiClient api;
  final String name;

  const _QrSheet({required this.api, required this.name});

  @override
  State<_QrSheet> createState() => _QrSheetState();
}

class _QrSheetState extends State<_QrSheet> {
  String? qr;
  String status = '正在获取二维码…';
  String? loginNick;
  bool loggedIn = false;
  bool loading = true;
  bool error = false;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  String _nick(Map info) => (info['nick'] ?? info['nickname'] ?? info['uin'] ?? 'QQ 已登录').toString();

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = false;
      status = '正在获取二维码…';
    });
    try {
      final d = Map<String, dynamic>.from(
        await widget.api.post('/api/napcat/qq-login', {'name': widget.name, 'action': 'qrcode'}) as Map,
      );
      if (!mounted) return;
      if (d['already_login'] == true) {
        setState(() {
          loggedIn = true;
          loading = false;
          loginNick = _nick(Map.from(d['login_info'] ?? {}));
          status = '机器人在线，无需再次扫码';
        });
        return;
      }
      setState(() {
        qr = d['qrcode_url']?.toString();
        loading = false;
        status = '请用手机 QQ 扫码，或截图后在 QQ 中识别';
      });
      timer?.cancel();
      timer = Timer.periodic(const Duration(milliseconds: 2500), (_) => _poll());
    } catch (e) {
      if (!mounted) return;
      setState(() {
        loading = false;
        error = true;
        status = e is ApiException ? e.message : e.toString();
      });
    }
  }

  Future<void> _poll() async {
    try {
      final r = Map<String, dynamic>.from(
        await widget.api.post('/api/napcat/qq-login', {'name': widget.name, 'action': 'status'}) as Map,
      );
      final d = Map<String, dynamic>.from(r['data'] ?? {});
      if (!mounted) return;
      if (d['isLogin'] == true) {
        timer?.cancel();
        setState(() {
          loggedIn = true;
          loginNick = _nick(Map.from(d['loginInfo'] ?? {}));
          status = '登录成功';
        });
      } else if (d['isOffline'] == true) {
        setState(() => status = '账号离线，请重新扫码');
      } else if ((d['loginError'] ?? '').toString().isNotEmpty) {
        setState(() => status = d['loginError'].toString());
      }
    } catch (_) {}
  }

  Future<void> _refresh() async {
    timer?.cancel();
    setState(() {
      loading = true;
      status = '正在刷新二维码…';
    });
    try {
      await widget.api.post('/api/napcat/qq-login', {'name': widget.name, 'action': 'refresh'});
    } catch (_) {}
    await Future.delayed(const Duration(milliseconds: 900));
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('${botName(widget.name)} · QQ 登录', style: tt.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: 20),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 250),
            child: SizedBox(
              key: ValueKey('$loggedIn$loading$error$qr'),
              width: 260,
              height: 260,
              child: loggedIn
                  ? Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        CircleAvatar(
                          radius: 44,
                          backgroundColor: cs.primaryContainer,
                          child: Icon(Icons.check_rounded, size: 52, color: cs.onPrimaryContainer),
                        ),
                        const SizedBox(height: 16),
                        Text(loginNick ?? '', style: tt.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                      ],
                    )
                  : loading
                  ? const LoadingView()
                  : error || qr == null
                  ? Icon(Icons.qr_code_2, size: 120, color: cs.outlineVariant)
                  : Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
                      child: QrImageView(data: qr!, backgroundColor: Colors.white),
                    ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            status,
            textAlign: TextAlign.center,
            style: TextStyle(color: error ? cs.error : cs.onSurfaceVariant),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              if (!loggedIn) ...[
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: loading ? null : _refresh,
                    icon: const Icon(Icons.refresh),
                    label: const Text('刷新二维码'),
                  ),
                ),
                const SizedBox(width: 12),
              ],
              Expanded(
                child: FilledButton(onPressed: () => Navigator.pop(context), child: Text(loggedIn ? '完成' : '关闭')),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
