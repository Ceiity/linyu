import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';
import 'home_shell.dart';

/// QQ 登录：展示 NapCat 登录二维码、刷新二维码、查看登录状态。
class QqPage extends StatefulWidget {
  final bool active;

  const QqPage({super.key, required this.active});

  @override
  State<QqPage> createState() => _QqPageState();
}

class _QqPageState extends State<QqPage> with WidgetsBindingObserver, PollingMixin {
  List<Map<String, dynamic>>? instances;
  String? selected;
  Map<String, dynamic>? login;
  String? error;
  bool refreshing = false;

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
  void didUpdateWidget(QqPage old) {
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
      if (instances == null) {
        final rows = (await api.get('/api/napcat') as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
        if (!mounted) return;
        setState(() {
          instances = rows;
          selected ??= rows.isEmpty ? null : rows.first['container'] as String;
        });
      }
      if (selected == null) return;
      final l = Map<String, dynamic>.from(await api.get('/api/napcat/$selected/login') as Map);
      if (!mounted) return;
      setState(() {
        login = l;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _refresh() async {
    final api = ConnScope.of(context).api;
    if (api == null || selected == null) return;
    setState(() => refreshing = true);
    final r = await runAction(context, () => api.post('/api/napcat/$selected/qrcode/refresh'));
    if (!mounted) return;
    setState(() {
      refreshing = false;
      if (r is Map) login = Map<String, dynamic>.from(r);
    });
  }

  Future<void> _action(String action) async {
    final api = ConnScope.of(context).api;
    if (api == null || selected == null) return;
    if (action != 'start' &&
        !await confirmDialog(
          context,
          title: '${action == 'stop' ? '停止' : '重启'} $selected？',
          destructive: action == 'stop',
        )) {
      return;
    }
    if (!mounted) return;
    await runAction(
      context,
      () => api.post('/api/services/napcat/$action?name=$selected', null, const Duration(seconds: 120)),
      success: '操作成功',
    );
    setState(() => instances = null);
    poll();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final rows = instances;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: poll,
        child: CustomScrollView(
          slivers: [
            const SliverAppBar.large(title: Text('QQ 登录')),
            if (rows == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error != null
                    ? MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: poll)
                    : offlinePlaceholder(context),
              )
            else if (rows.isEmpty)
              const SliverFillRemaining(
                hasScrollBody: false,
                child: MessageView(icon: Icons.chat_bubble_outline, text: '没有接管的 NapCat 实例'),
              )
            else
              SliverList.list(
                children: [
                  if (rows.length > 1)
                    SizedBox(
                      height: 48,
                      child: ListView(
                        scrollDirection: Axis.horizontal,
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        children: [
                          for (final r in rows)
                            Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: ChoiceChip(
                                label: Text(r['container'].toString()),
                                selected: selected == r['container'],
                                onSelected: (_) {
                                  setState(() {
                                    selected = r['container'] as String;
                                    login = null;
                                  });
                                  poll();
                                },
                              ),
                            ),
                        ],
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: _loginCard(cs, rows.firstWhere((r) => r['container'] == selected)),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _loginCard(ColorScheme cs, Map<String, dynamic> inst) {
    final l = login;
    final running = inst['running'] == true;
    return Column(
      children: [
        InfoCard(
          icon: Icons.chat_bubble_outline,
          title: inst['container'].toString(),
          actions: [
            StatusChip(containerStatusText(inst['state']?.toString()), containerTone(inst['state']?.toString())),
          ],
          child: Column(
            children: [
              if (!running)
                const Padding(padding: EdgeInsets.all(24), child: Text('NapCat 未运行，启动后才能登录 QQ'))
              else if (l == null)
                const SizedBox(height: 260, child: LoadingView())
              else if (l['is_login'] == true)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 24),
                  child: Column(
                    children: [
                      CircleAvatar(
                        radius: 40,
                        backgroundColor: cs.primaryContainer,
                        child: Icon(Icons.check_rounded, size: 48, color: cs.onPrimaryContainer),
                      ),
                      const SizedBox(height: 14),
                      Text(
                        l['nick']?.toString().isNotEmpty == true ? l['nick'].toString() : 'QQ 已登录',
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 4),
                      Text('QQ ${l['uin'] ?? ''}', style: TextStyle(color: cs.onSurfaceVariant)),
                      const SizedBox(height: 12),
                      const StatusChip('在线 · 已连接 AstrBot', Tone.ok),
                    ],
                  ),
                )
              else ...[
                const SizedBox(height: 8),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 250),
                  child: (l['qrcode'] ?? '').toString().isEmpty
                      ? SizedBox(
                          key: const ValueKey('noqr'),
                          height: 240,
                          child: Center(child: Icon(Icons.qr_code_2, size: 140, color: cs.outlineVariant)),
                        )
                      : Container(
                          key: ValueKey(l['qrcode']),
                          width: 240,
                          height: 240,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
                          child: QrImageView(data: l['qrcode'].toString(), backgroundColor: Colors.white),
                        ),
                ),
                const SizedBox(height: 14),
                Text(
                  (l['error'] ?? '').toString().isNotEmpty
                      ? l['error'].toString()
                      : (l['is_offline'] == true ? '账号离线，请重新扫码' : '用手机 QQ 扫码登录；也可以截图后在 QQ 中识别'),
                  textAlign: TextAlign.center,
                  style: TextStyle(color: (l['error'] ?? '').toString().isNotEmpty ? cs.warning : cs.onSurfaceVariant),
                ),
                const SizedBox(height: 14),
                FilledButton.tonalIcon(
                  onPressed: refreshing ? null : _refresh,
                  icon: refreshing
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.refresh),
                  label: const Text('刷新二维码'),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        GroupCard(
          children: [
            if (!running)
              ListTile(
                leading: const Icon(Icons.play_arrow_rounded),
                title: const Text('启动 NapCat'),
                onTap: () => _action('start'),
              ),
            ListTile(
              leading: const Icon(Icons.restart_alt_rounded),
              title: const Text('重启 NapCat'),
              onTap: () => _action('restart'),
            ),
            if (running)
              ListTile(
                leading: Icon(Icons.stop_rounded, color: cs.error),
                title: Text('停止 NapCat', style: TextStyle(color: cs.error)),
                onTap: () => _action('stop'),
              ),
          ],
        ),
      ],
    );
  }
}
