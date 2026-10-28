import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../core/ssh.dart';
import '../core/store.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'deploy_page.dart';

/// 首次打开：欢迎 + 服务器连接表单。也用于“添加服务器”和“重新配对”。
class WelcomePage extends StatefulWidget {
  final ServerProfile? repairFor;
  final bool pushed;

  const WelcomePage({super.key, this.repairFor, this.pushed = false});

  @override
  State<WelcomePage> createState() => _WelcomePageState();
}

class _WelcomePageState extends State<WelcomePage> {
  final _form = GlobalKey<FormState>();
  late final host = TextEditingController(text: widget.repairFor?.host ?? '');
  late final port = TextEditingController(text: '${widget.repairFor?.port ?? 22}');
  late final user = TextEditingController(text: widget.repairFor?.user ?? 'root');
  final password = TextEditingController();
  final keyPem = TextEditingController();
  final passphrase = TextEditingController();
  bool useKey = false;
  bool obscure = true;
  bool savePassword = false;

  @override
  void initState() {
    super.initState();
    final p = widget.repairFor;
    if (p != null) {
      StoreScope.read(context).secret('pw', p.id).then((v) {
        if (v != null && mounted) {
          setState(() {
            password.text = v;
            savePassword = true;
          });
        }
      });
    }
  }

  @override
  void dispose() {
    for (final c in [host, port, user, password, keyPem, passphrase]) {
      c.dispose();
    }
    super.dispose();
  }

  String? _validateHost(String? v) {
    final s = (v ?? '').trim();
    if (s.isEmpty) return '请输入服务器 IP 或域名';
    final ipv6 = RegExp(r'^[0-9a-fA-F:]+$').hasMatch(s) && s.contains(':');
    final ok = ipv6 || RegExp(r'^[A-Za-z0-9.\-]+$').hasMatch(s);
    return ok ? null : 'IP 或域名格式不正确';
  }

  Future<void> _importKey() async {
    final f = (await FilePicker.pickFiles()).firstOrNull;
    if (f == null) return;
    final bytes = await f.readAsBytes();
    if (bytes.length > 64 * 1024) return;
    setState(() => keyPem.text = String.fromCharCodes(bytes));
  }

  void _submit() {
    if (!_form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    final t = SshTarget(
      host: host.text.trim().replaceAll(RegExp(r'^\[|\]$'), ''),
      port: int.parse(port.text.trim()),
      user: user.text.trim(),
      password: password.text.isEmpty ? null : password.text,
      privateKeyPem: useKey ? keyPem.text : null,
      passphrase: useKey && passphrase.text.isNotEmpty ? passphrase.text : null,
    );
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DeployPage(target: t, savePassword: savePassword && !useKey, repairFor: widget.repairFor),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    final repair = widget.repairFor != null;
    return Scaffold(
      appBar: widget.pushed ? AppBar(title: Text(repair ? '重新配对' : '添加服务器')) : null,
      body: SafeArea(
        top: !widget.pushed,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Form(
              key: _form,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
                children: [
                  if (!widget.pushed) ...[
                    const Center(child: AppLogo(size: 112)),
                    const SizedBox(height: 12),
                    Text(
                      '欢迎使用奶龙',
                      textAlign: TextAlign.center,
                      style: tt.headlineMedium?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '轻松部署与管理你的 AstrBot。',
                      textAlign: TextAlign.center,
                      style: tt.bodyLarge?.copyWith(color: cs.onSurfaceVariant),
                    ),
                    const SizedBox(height: 28),
                  ],
                  InfoCard(
                    icon: Icons.dns_outlined,
                    title: '服务器信息',
                    child: Column(
                      children: [
                        TextFormField(
                          controller: host,
                          enabled: !repair,
                          keyboardType: TextInputType.url,
                          autocorrect: false,
                          validator: _validateHost,
                          decoration: const InputDecoration(
                            labelText: '服务器 IP',
                            hintText: '支持 IPv4、IPv6 和域名',
                            prefixIcon: Icon(Icons.public),
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            SizedBox(
                              width: 120,
                              child: TextFormField(
                                controller: port,
                                enabled: !repair,
                                keyboardType: TextInputType.number,
                                validator: (v) {
                                  final n = int.tryParse((v ?? '').trim());
                                  return n == null || n < 1 || n > 65535 ? '端口无效' : null;
                                },
                                decoration: const InputDecoration(labelText: 'SSH 端口'),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: TextFormField(
                                controller: user,
                                enabled: !repair,
                                autocorrect: false,
                                validator: (v) =>
                                    RegExp(r'^[a-z_][a-z0-9_\-.]{0,31}$').hasMatch((v ?? '').trim()) ? null : '用户名无效',
                                decoration: const InputDecoration(
                                  labelText: 'SSH 用户名',
                                  prefixIcon: Icon(Icons.person_outline),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  InfoCard(
                    icon: Icons.key_outlined,
                    title: '登录方式',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SegmentedButton<bool>(
                          segments: const [
                            ButtonSegment(value: false, icon: Icon(Icons.password), label: Text('密码')),
                            ButtonSegment(value: true, icon: Icon(Icons.vpn_key_outlined), label: Text('私钥')),
                          ],
                          selected: {useKey},
                          onSelectionChanged: (v) => setState(() => useKey = v.first),
                        ),
                        const SizedBox(height: 12),
                        if (useKey) ...[
                          TextFormField(
                            controller: keyPem,
                            minLines: 3,
                            maxLines: 6,
                            autocorrect: false,
                            style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                            validator: (v) =>
                                useKey && !(v ?? '').contains('PRIVATE KEY') ? '请粘贴 OpenSSH / PEM 私钥' : null,
                            decoration: InputDecoration(
                              labelText: 'SSH 私钥',
                              hintText: '-----BEGIN OPENSSH PRIVATE KEY-----',
                              suffixIcon: IconButton(
                                tooltip: '从文件导入',
                                icon: const Icon(Icons.folder_open),
                                onPressed: _importKey,
                              ),
                            ),
                          ),
                          const SizedBox(height: 12),
                          TextFormField(
                            controller: passphrase,
                            obscureText: true,
                            decoration: const InputDecoration(labelText: '私钥密码（没有可留空）'),
                          ),
                          const SizedBox(height: 12),
                          TextFormField(
                            controller: password,
                            obscureText: true,
                            decoration: const InputDecoration(labelText: 'sudo 密码（root 登录可留空）'),
                          ),
                        ] else ...[
                          TextFormField(
                            controller: password,
                            obscureText: obscure,
                            validator: (v) => !useKey && (v ?? '').isEmpty ? '请输入 SSH 密码' : null,
                            decoration: InputDecoration(
                              labelText: 'SSH 密码',
                              prefixIcon: const Icon(Icons.lock_outline),
                              suffixIcon: IconButton(
                                icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                                onPressed: () => setState(() => obscure = !obscure),
                              ),
                            ),
                          ),
                          CheckboxListTile(
                            contentPadding: EdgeInsets.zero,
                            value: savePassword,
                            onChanged: (v) => setState(() => savePassword = v ?? false),
                            controlAffinity: ListTileControlAffinity.leading,
                            title: const Text('在本机安全保存密码'),
                            subtitle: const Text('使用 Android Keystore 加密。默认不保存，日常管理不需要密码'),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _submit,
                    style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
                    icon: Icon(repair ? Icons.link : Icons.rocket_launch_outlined),
                    label: Text(repair ? '连接并重新配对' : '连接并自动部署', style: const TextStyle(fontSize: 16)),
                  ),
                  const SizedBox(height: 16),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.verified_user_outlined, size: 16, color: cs.accentText),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          '首次连接会显示服务器指纹供你核对。部署前会先展示检测报告并征得你的同意；'
                          '已有的 AstrBot / NapCat 只接管、不重装、不清空。部署完成后改用本机专属密钥，通过 SSH 隧道管理，不开放公网端口。',
                          style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant, height: 1.6),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 首次连接核对主机指纹。
Future<bool> confirmHostKey(BuildContext context, String host, String type, String fingerprint) async {
  final r = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (c) {
      final cs = Theme.of(c).colorScheme;
      return AlertDialog(
        icon: const Icon(Icons.fingerprint, size: 36),
        title: const Text('核对服务器身份'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('首次连接 $host，请核对服务器的 SSH 主机密钥指纹：'),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(12)),
              child: SelectableText(
                '$type\n$fingerprint',
                style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              '可在服务器控制台执行 ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 对比。确认无误后才信任，以后连接会自动校验。',
              style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('不信任')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('信任并连接')),
        ],
      );
    },
  );
  return r == true;
}
