import 'package:material_ui/material_ui.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../ui/widgets.dart';

class PanelSettingsPage extends StatefulWidget {
  const PanelSettingsPage({super.key});

  @override
  State<PanelSettingsPage> createState() => _PanelSettingsPageState();
}

const _textFields = [
  ('napcat_watchdog_interval', '检测间隔（秒）', true),
  ('napcat_watchdog_abnormal_threshold', '连续异常次数', true),
  ('napcat_recovery_max', '最大恢复次数', true),
  ('napcat_recovery_window', '恢复统计窗口（秒）', true),
  ('napcat_recovery_wait', '恢复等待时间（秒）', true),
  ('linyu_remote_owner_ids', '主人 QQ（逗号分隔）', false),
  ('linyu_remote_bot_self_ids', '机器人 QQ（逗号分隔）', false),
  ('linyu_remote_allowed_groups', '允许的群（留空不限）', false),
  ('linyu_remote_triggers', '触发词', false),
  ('linyu_remote_server_url', '远程 API 地址（留空自动）', false),
  ('public_base_url', '公网访问地址（通常留空）', false),
  ('default_reverse_ws_token', '默认连接 Token', false),
];

const _switches = [
  ('napcat_watchdog_enabled', '掉线自动恢复', '检测到 QQ 掉线时自动重启机器人'),
  ('linyu_remote_login_enabled', 'QQ 远程申请登录', '在 QQ 里发送触发词创建机器人'),
  ('allow_dangerous', '允许危险操作', '恢复备份、完全删除数据等'),
];

class _PanelSettingsPageState extends State<PanelSettingsPage> {
  Map<String, dynamic>? cfg;
  Map<String, dynamic>? watchdog;
  String? error;
  bool saving = false;
  final ctrls = <String, TextEditingController>{};
  final flags = <String, bool>{};

  ApiClient get api => AppScope.read(context).api!;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in ctrls.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final c = Map<String, dynamic>.from(await api.get('/api/settings') as Map);
      Map<String, dynamic>? w;
      try {
        w = Map<String, dynamic>.from(await api.get('/api/watchdog/status') as Map);
      } catch (_) {}
      if (!mounted) return;
      for (final f in _textFields) {
        (ctrls[f.$1] ??= TextEditingController()).text = (c[f.$1] ?? '').toString();
      }
      for (final s in _switches) {
        flags[s.$1] = c[s.$1] == true;
      }
      setState(() {
        cfg = c;
        watchdog = w;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _save() async {
    final patch = <String, dynamic>{};
    for (final f in _textFields) {
      final v = ctrls[f.$1]!.text.trim();
      if (f.$3) {
        final n = int.tryParse(v);
        if (n == null) return toast(context, '${f.$2} 必须是数字');
        patch[f.$1] = n;
      } else {
        patch[f.$1] = v;
      }
    }
    patch.addAll(flags);
    setState(() => saving = true);
    final r = await runAction(context, () => api.post('/api/settings', patch), success: '设置已保存');
    if (mounted) setState(() => saving = false);
    if (r != null) _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final w = watchdog;
    return Scaffold(
      floatingActionButton: cfg == null
          ? null
          : FloatingActionButton.extended(
              onPressed: saving ? null : _save,
              icon: saving
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.save_outlined),
              label: const Text('保存'),
            ),
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('面板设置')),
          if (cfg == null)
            SliverFillRemaining(
              hasScrollBody: false,
              child: error == null
                  ? const LoadingView()
                  : MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: _load),
            )
          else
            SliverList.list(
              children: [
                if (w != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: InfoCard(
                      icon: Icons.health_and_safety_outlined,
                      title: '掉线守护服务',
                      actions: [
                        StatusChip(
                          w['service']?.toString().isEmpty ?? true ? 'unknown' : w['service'].toString(),
                          w['service'] == 'active' ? Tone.ok : Tone.warn,
                        ),
                      ],
                      child: SizedBox(
                        width: double.infinity,
                        child: FilledButton.tonalIcon(
                          icon: const Icon(Icons.restart_alt),
                          label: const Text('重启守护服务'),
                          onPressed: () async {
                            await runAction(context, () => api.post('/api/watchdog/restart'), success: '已重启');
                            _load();
                          },
                        ),
                      ),
                    ),
                  ),
                const SectionTitle('开关'),
                GroupCard(
                  children: [
                    for (final s in _switches)
                      SwitchListTile(
                        title: Text(s.$2),
                        subtitle: Text(s.$3),
                        value: flags[s.$1] ?? false,
                        onChanged: (v) => setState(() => flags[s.$1] = v),
                      ),
                  ],
                ),
                const SectionTitle('掉线守护'),
                ..._fields(0, 5),
                const SectionTitle('QQ 远程登录'),
                ..._fields(5, 10),
                const SectionTitle('高级'),
                ..._fields(10, 12),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
                  child: Text('安装目录、上传目录等路径类设置请在网页面板修改。', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
                ),
                const SizedBox(height: 96),
              ],
            ),
        ],
      ),
    );
  }

  List<Widget> _fields(int from, int to) => [
    for (final f in _textFields.sublist(from, to))
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: TextField(
          controller: ctrls[f.$1],
          keyboardType: f.$3 ? TextInputType.number : TextInputType.text,
          decoration: InputDecoration(labelText: f.$2),
        ),
      ),
  ];
}

class AccountPage extends StatefulWidget {
  const AccountPage({super.key});

  @override
  State<AccountPage> createState() => _AccountPageState();
}

class _AccountPageState extends State<AccountPage> {
  final oldPwd = TextEditingController();
  final newPwd = TextEditingController();
  final newPwd2 = TextEditingController();
  bool busy = false;

  @override
  void dispose() {
    oldPwd.dispose();
    newPwd.dispose();
    newPwd2.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (newPwd.text != newPwd2.text) return toast(context, '两次新密码不一致');
    if (newPwd.text.length < 10) return toast(context, '新密码至少需要 10 位');
    final s = AppScope.read(context);
    setState(() => busy = true);
    final r = await runAction(
      context,
      () => s.api!.post('/api/account/password', {'old_password': oldPwd.text, 'new_password': newPwd.text}),
    );
    if (!mounted) return;
    setState(() => busy = false);
    if (r != null) {
      toast(context, '密码已修改，所有设备已退出登录');
      Navigator.of(context).popUntil((r) => r.isFirst);
      await s.logout();
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    Widget field(TextEditingController c, String label) => Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: TextField(
        controller: c,
        obscureText: true,
        decoration: InputDecoration(labelText: label),
      ),
    );
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('账号安全')),
          SliverList.list(
            children: [
              const SectionTitle('修改面板密码'),
              field(oldPwd, '当前密码'),
              field(newPwd, '新密码（至少 10 位，含两类字符）'),
              field(newPwd2, '确认新密码'),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: FilledButton(
                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
                  onPressed: busy ? null : _submit,
                  child: busy
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('修改密码'),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(20),
                child: Text('修改后所有设备（含网页面板）都会退出登录。', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
