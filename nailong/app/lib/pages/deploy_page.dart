import 'package:material_ui/material_ui.dart';

import '../core/deploy_flow.dart';
import '../core/errors.dart';
import '../core/ssh.dart';
import '../core/store.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'sources_page.dart';
import 'welcome_page.dart';

class DeployPage extends StatefulWidget {
  final SshTarget target;
  final bool savePassword;
  final ServerProfile? repairFor;

  /// 仅用于截图/测试：注入已有流程状态，不发起连接。
  final DeployFlow? debugFlow;

  const DeployPage({super.key, required this.target, this.savePassword = false, this.repairFor, this.debugFlow});

  @override
  State<DeployPage> createState() => _DeployPageState();
}

class _DeployPageState extends State<DeployPage> {
  late final DeployFlow flow =
      widget.debugFlow ?? (DeployFlow(StoreScope.read(context))..savePassword = widget.savePassword);
  bool showLogs = false;

  @override
  void initState() {
    super.initState();
    flow.addListener(() => mounted ? setState(() {}) : null);
    if (widget.debugFlow == null) WidgetsBinding.instance.addPostFrameCallback((_) => _start());
  }

  Future<bool> _decide(String type, String fp, String? known) =>
      confirmHostKey(context, '${widget.target.host}:${widget.target.port}', type, fp);

  Future<void> _start() async {
    if (widget.repairFor != null) {
      await flow.repair(widget.target, widget.repairFor!, _decide);
    } else {
      await flow.connectAndDetect(widget.target, _decide);
    }
  }

  @override
  void dispose() {
    flow.dispose();
    super.dispose();
  }

  Future<bool> _confirmLeave() async {
    if (flow.phase != FlowPhase.deploying && flow.phase != FlowPhase.pairing) return true;
    final leave = await confirmDialog(
      context,
      title: '部署进行中',
      message: '离开会中断与服务器的连接。服务器上已完成的步骤会保留，之后可以继续部署。确定离开吗？',
      confirmText: '离开',
      destructive: true,
    );
    return leave;
  }

  @override
  Widget build(BuildContext context) {
    final phase = flow.phase;
    return PopScope(
      canPop: phase != FlowPhase.deploying && phase != FlowPhase.pairing,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (await _confirmLeave() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        body: CustomScrollView(
          slivers: [
            SliverAppBar.large(
              title: Text(switch (phase) {
                FlowPhase.report => '环境检测报告',
                FlowPhase.success => '部署成功',
                FlowPhase.deploying || FlowPhase.pairing => '正在部署',
                FlowPhase.failed => '部署未完成',
                FlowPhase.cancelled => '已取消',
                _ => '连接服务器',
              }),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 120),
              sliver: SliverList.list(
                children: switch (phase) {
                  FlowPhase.report => _report(),
                  FlowPhase.success => _success(),
                  _ => _progress(),
                },
              ),
            ),
          ],
        ),
        bottomNavigationBar: _bottomBar(),
      ),
    );
  }

  Widget? _bottomBar() {
    final cs = Theme.of(context).colorScheme;
    Widget bar(List<Widget> children) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Row(children: children),
      ),
    );
    switch (flow.phase) {
      case FlowPhase.report:
        final blocked = flow.blockers.isNotEmpty;
        final takeover = flow.plan['mode'] == 'takeover';
        return bar([
          Expanded(
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(54)),
              onPressed: blocked ? null : flow.deploy,
              icon: Icon(takeover ? Icons.handshake_outlined : Icons.rocket_launch),
              label: Text(blocked ? '无法部署' : (takeover ? '接管并配对' : '确认并开始部署')),
            ),
          ),
        ]);
      case FlowPhase.deploying:
        return bar([
          Expanded(
            child: OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52), foregroundColor: cs.error),
              onPressed: flow.cancelRequested ? null : flow.cancel,
              icon: const Icon(Icons.stop_circle_outlined),
              label: Text(flow.cancelRequested ? '正在安全停止…' : '取消部署'),
            ),
          ),
        ]);
      case FlowPhase.failed:
      case FlowPhase.cancelled:
        final canContinue = flow.installer != null && flow.report != null && flow.error?.code != 'HOSTKEY_CHANGED';
        return bar([
          Expanded(
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('返回'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
              onPressed: canContinue && !(flow.ssh?.isClosed ?? true) ? flow.deploy : _start,
              icon: const Icon(Icons.refresh),
              label: Text(canContinue ? '继续部署' : '重试'),
            ),
          ),
        ]);
      case FlowPhase.success:
        return bar([
          Expanded(
            child: FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
              onPressed: () => Navigator.of(context).popUntil((r) => r.isFirst),
              icon: const Icon(Icons.dashboard_outlined),
              label: const Text('进入奶龙管理首页'),
            ),
          ),
        ]);
      default:
        return null;
    }
  }

  // ---------------------------------------------------------------- 进度

  List<Widget> _progress() {
    final cs = Theme.of(context).colorScheme;
    return [
      if (flow.error != null) _errorCard(flow.error!),
      if (flow.phase == FlowPhase.connecting ||
          flow.phase == FlowPhase.detecting ||
          flow.phase == FlowPhase.deploying ||
          flow.phase == FlowPhase.pairing)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Row(
            children: [
              const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.5)),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  flow.status,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: cs.onSurfaceVariant),
                ),
              ),
            ],
          ),
        ),
      InfoCard(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(children: [for (final s in flow.steps) _StepTile(step: s)]),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.terminal,
        title: '部署日志（${flow.logs.length}）',
        onTap: () => setState(() => showLogs = !showLogs),
        actions: [Icon(showLogs ? Icons.expand_less : Icons.expand_more, color: cs.onSurfaceVariant)],
        child: showLogs
            ? Container(
                height: 280,
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(12)),
                child: ListView.builder(
                  reverse: true,
                  itemCount: flow.logs.length,
                  itemBuilder: (_, i) => Text(
                    flow.logs[flow.logs.length - 1 - i],
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11, height: 1.4),
                  ),
                ),
              )
            : Text('点击展开实时日志', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
      ),
    ];
  }

  Widget _errorCard(NailongError e) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: cs.errorContainer,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.error_outline, color: cs.onErrorContainer),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      e.message,
                      style: TextStyle(color: cs.onErrorContainer, fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
              if (installerHints[e.code] != null && installerHints[e.code] != e.message) ...[
                const SizedBox(height: 8),
                Text(installerHints[e.code]!, style: TextStyle(color: cs.onErrorContainer)),
              ],
              if (e.code == 'IMAGE_PULL_FAILED' ||
                  e.code == 'DOCKER_SOURCE_FAILED' ||
                  e.code == 'AGENT_DEPS_FAILED') ...[
                const SizedBox(height: 10),
                FilledButton.tonalIcon(
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SourcesPage())),
                  icon: const Icon(Icons.speed),
                  label: const Text('设置下载加速'),
                ),
              ],
              if (e.detail.isNotEmpty) ...[
                const SizedBox(height: 8),
                Theme(
                  data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                  child: ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    title: Text('技术详情', style: TextStyle(color: cs.onErrorContainer, fontSize: 13)),
                    children: [
                      SelectableText(
                        e.detail,
                        style: TextStyle(color: cs.onErrorContainer, fontSize: 11, fontFamily: 'monospace'),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  // ---------------------------------------------------------------- 报告

  List<Widget> _report() {
    final r = flow.report!;
    final cs = Theme.of(context).colorScheme;
    final os = Map<String, dynamic>.from(r['os'] as Map);
    final res = Map<String, dynamic>.from(r['resources'] as Map);
    final tools = Map<String, dynamic>.from(r['tools'] as Map);
    final docker = Map<String, dynamic>.from(r['docker'] as Map);
    final existing = Map<String, dynamic>.from(r['existing'] as Map);
    final net = Map<String, dynamic>.from((r['network'] ?? {}) as Map);
    final fw = Map<String, dynamic>.from((r['firewall'] ?? {}) as Map);
    final plan = flow.plan;
    final mode = plan['mode'];
    Widget kv(String k, String v, {Tone? tone}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          SizedBox(
            width: 96,
            child: Text(k, style: TextStyle(color: cs.onSurfaceVariant)),
          ),
          Expanded(
            child: Text(
              v,
              style: TextStyle(fontWeight: FontWeight.w600, color: tone == null ? null : toneColor(cs, tone)),
            ),
          ),
        ],
      ),
    );
    return [
      InfoCard(
        selected: true,
        child: Row(
          children: [
            Icon(
              mode == 'takeover'
                  ? Icons.handshake
                  : (mode == 'fresh' ? Icons.auto_awesome : Icons.build_circle_outlined),
              size: 36,
              color: cs.onSecondaryContainer,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(switch (mode) {
                    'takeover' => '检测到已有 AstrBot 和 NapCat',
                    'fresh' => '全新服务器',
                    _ => '部分组件已存在',
                  }, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 4),
                  Text(switch (mode) {
                    'takeover' => '将保留现有配置与数据，只安装奶龙 Agent 并完成配对',
                    'fresh' => '将从零安装 Docker、AstrBot、NapCat 并自动配置',
                    _ => '只补齐缺失的组件，已有服务保持不变',
                  }, style: TextStyle(color: cs.onSecondaryContainer)),
                ],
              ),
            ),
          ],
        ),
      ),
      for (final b in flow.blockers) _note(Icons.block, b, cs.error),
      for (final w in (plan['warnings'] as List? ?? [])) _note(Icons.warning_amber, w.toString(), cs.warning),
      const SectionTitle('部署计划'),
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: InfoCard(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
          child: SwitchListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 12),
            secondary: const Icon(Icons.shield_outlined),
            title: const Text('安装 Fail2Ban（推荐）', style: TextStyle(fontWeight: FontWeight.w700)),
            subtitle: const Text('防 SSH 暴力破解 / 撞库：连续输错 5 次密码封禁该 IP 1 小时。已有 Fail2Ban 保护时保留原配置'),
            value: flow.installFail2ban,
            onChanged: (v) => setState(() => flow.installFail2ban = v),
          ),
        ),
      ),
      InfoCard(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(
          children: [
            for (final s in (plan['steps'] as List).map((e) {
              final m = Map<String, dynamic>.from(e as Map);
              if (m['id'] == 'fail2ban' && !flow.installFail2ban) m['action'] = 'skip';
              return m;
            }))
              ListTile(
                dense: true,
                leading: Icon(switch (s['action']) {
                  'install' => Icons.download_rounded,
                  'upgrade' => Icons.upgrade,
                  'keep' => Icons.shield_outlined,
                  _ => Icons.check_circle_outline,
                }, color: s['action'] == 'keep' ? cs.success : (s['action'] == 'skip' ? cs.outline : cs.accentText)),
                title: Text(s['title'].toString(), style: const TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text(s['detail'].toString()),
                trailing: StatusChip(
                  switch (s['action']) {
                    'install' => '将安装',
                    'upgrade' => '将升级',
                    'keep' => '保留',
                    _ => '跳过',
                  },
                  switch (s['action']) {
                    'keep' => Tone.ok,
                    'skip' => Tone.idle,
                    _ => Tone.info,
                  },
                  dot: false,
                ),
              ),
          ],
        ),
      ),
      const SectionTitle('服务器环境'),
      InfoCard(
        icon: Icons.computer,
        title: '系统',
        child: Column(
          children: [
            kv('系统', '${os['pretty']}', tone: os['supported'] == true ? null : Tone.bad),
            kv('架构', '${os['machine']}'),
            kv('内核', '${os['kernel']}'),
            kv('主机名', '${r['hostname']}'),
            kv('权限', r['is_root'] == true ? 'root' : '非 root', tone: r['is_root'] == true ? Tone.ok : Tone.bad),
          ],
        ),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.memory,
        title: '资源',
        child: Column(
          children: [
            kv('CPU', '${res['cpu_cores']} 核'),
            kv('内存', '${fmtBytes(res['mem_available'] as num?)} 可用 / ${fmtBytes(res['mem_total'] as num?)}'),
            kv('磁盘', '${fmtBytes(res['disk_free'] as num?)} 可用 / ${fmtBytes(res['disk_total'] as num?)}'),
          ],
        ),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.inventory_2_outlined,
        title: '已有服务',
        child: Column(
          children: [
            kv(
              'Docker',
              docker['installed'] == true
                  ? '${docker['version'] ?? '已安装'}${docker['running'] == true ? '' : '（未运行）'}'
                  : '未安装',
              tone: docker['installed'] == true ? Tone.ok : Tone.idle,
            ),
            kv('Compose', docker['compose'] == true ? '已安装' : '未安装'),
            kv(
              'AstrBot',
              (existing['astrbot'] as List).isEmpty ? '未发现' : (existing['astrbot'] as List).join('、'),
              tone: (existing['astrbot'] as List).isEmpty ? Tone.idle : Tone.ok,
            ),
            kv(
              'NapCat',
              (existing['napcat'] as List).isEmpty ? '未发现' : (existing['napcat'] as List).join('、'),
              tone: (existing['napcat'] as List).isEmpty ? Tone.idle : Tone.ok,
            ),
            kv('奶龙 Agent', (existing['agent'] as List).isEmpty ? '未安装' : '已安装（将升级）'),
            kv('容器', '${(r['containers'] as List? ?? []).length} 个'),
            kv('网络 / 数据卷', '${(r['networks'] as List? ?? []).length} / ${(r['volumes'] as List? ?? []).length}'),
          ],
        ),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.handyman_outlined,
        title: '基础工具',
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [for (final e in tools.entries) StatusChip(e.key, e.value == null ? Tone.idle : Tone.ok)],
        ),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.lan_outlined,
        title: '网络与安全',
        actions: [
          TextButton.icon(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SourcesPage())),
            icon: const Icon(Icons.speed, size: 18),
            label: const Text('下载加速'),
          ),
        ],
        child: Column(
          children: [
            for (final e in net.entries)
              kv(
                e.key.replaceAll('registry-1.docker.io', 'Docker Hub').replaceAll('download.docker.com', 'Docker 软件源'),
                e.value['https'] == true
                    ? '正常 ${e.value['latency_ms']} ms'
                    : (e.value['dns'] == true ? 'HTTPS 不可达' : 'DNS 解析失败'),
                tone: e.value['https'] == true ? Tone.ok : Tone.warn,
              ),
            kv(
              '防火墙',
              [
                if (fw['ufw'] != null) 'UFW ${fw['ufw']}',
                if (fw['firewalld'] != null) 'firewalld ${fw['firewalld']}',
              ].join('，').ifEmpty('未检测到'),
            ),
            kv(
              'SSH 隧道',
              r['sshd']?['ok'] == false ? '已被禁用' : '可用',
              tone: r['sshd']?['ok'] == false ? Tone.bad : Tone.ok,
            ),
          ],
        ),
      ),
    ];
  }

  Widget _note(IconData icon, String text, Color color) => Padding(
    padding: const EdgeInsets.only(top: 10),
    child: Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: TextStyle(color: color, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    ),
  );

  // ---------------------------------------------------------------- 成功

  List<Widget> _success() {
    final cs = Theme.of(context).colorScheme;
    final p = flow.result!;
    return [
      const SizedBox(height: 12),
      const Center(child: AppLogo(size: 140)),
      const SizedBox(height: 12),
      Text(
        '🎉 部署成功！',
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 8),
      Text(
        '以后打开奶龙会自动安全连接到 ${p.name}',
        textAlign: TextAlign.center,
        style: TextStyle(color: cs.onSurfaceVariant),
      ),
      const SizedBox(height: 24),
      InfoCard(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(children: [for (final s in flow.steps) _StepTile(step: s)]),
      ),
      const SizedBox(height: 12),
      InfoCard(
        icon: Icons.qr_code_2,
        title: '下一步',
        child: Text('进入首页后，在「QQ」页扫码登录机器人账号，NapCat 会自动连接到 AstrBot。', style: TextStyle(color: cs.onSurfaceVariant)),
      ),
    ];
  }
}

extension on String {
  String ifEmpty(String other) => isEmpty ? other : this;
}

class _StepTile extends StatelessWidget {
  final DeployStep step;

  const _StepTile({required this.step});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final (icon, color) = switch (step.status) {
      StepStatus.done => (Icons.check_circle, cs.success),
      StepStatus.kept => (Icons.shield, cs.success),
      StepStatus.skipped => (Icons.remove_circle_outline, cs.outline),
      StepStatus.warning => (Icons.warning_amber_rounded, cs.warning),
      StepStatus.failed => (Icons.cancel, cs.error),
      StepStatus.running => (Icons.timelapse, cs.primary),
      StepStatus.pending => (Icons.radio_button_unchecked, cs.outlineVariant),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 24,
            height: 24,
            child: step.status == StepStatus.running
                ? Padding(
                    padding: const EdgeInsets.all(3),
                    child: CircularProgressIndicator(strokeWidth: 2.5, color: color),
                  )
                : Icon(icon, color: color, size: 22),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        step.title,
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: step.status == StepStatus.pending ? cs.onSurfaceVariant : null,
                        ),
                      ),
                    ),
                    if (step.speed != null)
                      Text(fmtSpeed(step.speed), style: TextStyle(fontSize: 12, color: cs.accentText)),
                  ],
                ),
                if (step.message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      step.message,
                      style: TextStyle(
                        fontSize: 12.5,
                        color: step.status == StepStatus.failed ? cs.error : cs.onSurfaceVariant,
                      ),
                    ),
                  ),
                if (step.status == StepStatus.running && step.percent != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(99),
                      child: LinearProgressIndicator(value: step.percent! / 100, minHeight: 6),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
