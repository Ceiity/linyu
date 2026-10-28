import 'package:material_ui/material_ui.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../ui/widgets.dart';

class ServerPage extends StatefulWidget {
  const ServerPage({super.key});

  @override
  State<ServerPage> createState() => _ServerPageState();
}

class _ServerPageState extends State<ServerPage> {
  final ctrl = TextEditingController();
  bool busy = false;
  String? error;
  String stage = '';

  @override
  void dispose() {
    ctrl.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    final input = ctrl.text.trim();
    if (input.isEmpty) {
      setState(() => error = '请输入服务器 IP 或域名');
      return;
    }
    if (panelCandidates(input).isEmpty) {
      setState(() => error = '地址格式不正确');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      busy = true;
      error = null;
      stage = '正在探测面板端口 7070…';
    });
    final r = await discoverPanel(input);
    if (!mounted) return;
    if (r == null) {
      setState(() {
        busy = false;
        error = '未找到面板。请确认：\n1. 服务器已安装淋雨面板\n2. 安全组已放行 7070 端口\n3. 地址填写正确';
      });
      return;
    }
    setState(() => stage = '已找到 ${Uri.parse(r.baseUrl).authority}');
    await AppScope.read(context).useServer(r.baseUrl, version: r.version);
  }

  Future<void> _openSaved(ServerEntry s) async {
    setState(() {
      busy = true;
      error = null;
      stage = '正在连接 ${s.host}…';
    });
    final r = await discoverPanel(s.baseUrl);
    if (!mounted) return;
    if (r == null) {
      setState(() {
        busy = false;
        error = '${s.host} 无法连接';
      });
      return;
    }
    await AppScope.read(context).useServer(s.baseUrl, version: r.version);
  }

  Future<void> _manage(ServerEntry s) async {
    final state = AppScope.read(context);
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('重命名'),
              onTap: () => Navigator.pop(c, 'rename'),
            ),
            ListTile(
              leading: Icon(Icons.delete_outline, color: Theme.of(c).colorScheme.error),
              title: Text('删除', style: TextStyle(color: Theme.of(c).colorScheme.error)),
              onTap: () => Navigator.pop(c, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (!mounted) return;
    if (action == 'delete') {
      await state.removeServer(s);
    } else if (action == 'rename') {
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
      if (name != null) await state.renameServer(s, name);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final servers = AppScope.of(context).servers;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 40, 20, 24),
              children: [
                const Center(child: AppLogo(size: 84)),
                const SizedBox(height: 18),
                Text(
                  '淋雨',
                  textAlign: TextAlign.center,
                  style: tt.headlineMedium?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                Text(
                  'AstrBot 与 NapCat 机器人管理',
                  textAlign: TextAlign.center,
                  style: tt.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
                ),
                const SizedBox(height: 32),
                InfoCard(
                  icon: Icons.dns_outlined,
                  title: '连接服务器',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextField(
                        controller: ctrl,
                        enabled: !busy,
                        keyboardType: TextInputType.url,
                        autocorrect: false,
                        textInputAction: TextInputAction.go,
                        onSubmitted: (_) => _connect(),
                        decoration: const InputDecoration(
                          hintText: '服务器 IP，例如 1.2.3.4',
                          prefixIcon: Icon(Icons.public),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '只填 IP 会自动寻找 7070 端口；也支持 IP:端口 或 https://域名',
                        style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                      ),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: busy ? null : _connect,
                        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
                        icon: busy
                            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.link),
                        label: Text(busy ? stage : '连接'),
                      ),
                      if (error != null) ...[
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(color: cs.errorContainer, borderRadius: BorderRadius.circular(12)),
                          child: Text(error!, style: TextStyle(color: cs.onErrorContainer, height: 1.5)),
                        ),
                      ],
                    ],
                  ),
                ),
                if (servers.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const SectionTitle('已保存的服务器'),
                  for (final s in servers)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: Material(
                        color: cs.surfaceContainer,
                        borderRadius: BorderRadius.circular(16),
                        clipBehavior: Clip.antiAlias,
                        child: ListTile(
                          enabled: !busy,
                          contentPadding: const EdgeInsets.fromLTRB(16, 4, 4, 4),
                          leading: CircleAvatar(
                            backgroundColor: cs.primaryContainer,
                            child: Icon(Icons.dns, color: cs.onPrimaryContainer, size: 20),
                          ),
                          title: Text(s.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle: Text(s.baseUrl, maxLines: 1, overflow: TextOverflow.ellipsis),
                          trailing: IconButton(icon: const Icon(Icons.more_vert), onPressed: () => _manage(s)),
                          onTap: () => _openSaved(s),
                          onLongPress: () => _manage(s),
                        ),
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class AppLogo extends StatelessWidget {
  final double size;

  const AppLogo({super.key, this.size = 64});

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(size * 0.29),
      child: Image.asset('assets/logo.png', width: size, height: size, fit: BoxFit.cover),
    );
  }
}
