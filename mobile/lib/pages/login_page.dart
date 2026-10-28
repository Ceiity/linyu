import 'package:material_ui/material_ui.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../ui/widgets.dart';
import 'server_page.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final user = TextEditingController();
  final pass = TextEditingController();
  bool busy = false;
  bool obscure = true;
  String? error;

  @override
  void dispose() {
    user.dispose();
    pass.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (user.text.trim().isEmpty || pass.text.isEmpty) {
      setState(() => error = '请输入账号和密码');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await AppScope.read(context).login(user.text.trim(), pass.text);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = e.code == 'RATE_LIMIT' ? '登录尝试过多，请 30 分钟后再试' : e.message;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    final tt = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(icon: const Icon(Icons.arrow_back), onPressed: busy ? null : s.leaveServer),
      ),
      body: SafeArea(
        top: false,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
              children: [
                const Center(child: AppLogo(size: 72)),
                const SizedBox(height: 16),
                Text(
                  '登录面板',
                  textAlign: TextAlign.center,
                  style: tt.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 8),
                Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(color: cs.surfaceContainerHigh, borderRadius: BorderRadius.circular(99)),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.dns, size: 14, color: cs.primary),
                        const SizedBox(width: 6),
                        Text(s.current?.host ?? '', style: tt.labelMedium),
                        if ((s.current?.version ?? '').isNotEmpty)
                          Text('  v${s.current!.version}', style: tt.labelMedium?.copyWith(color: cs.onSurfaceVariant)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                InfoCard(
                  child: AutofillGroup(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextField(
                          controller: user,
                          enabled: !busy,
                          autocorrect: false,
                          autofillHints: const [AutofillHints.username],
                          textInputAction: TextInputAction.next,
                          decoration: const InputDecoration(hintText: '面板账号', prefixIcon: Icon(Icons.person_outline)),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: pass,
                          enabled: !busy,
                          obscureText: obscure,
                          autofillHints: const [AutofillHints.password],
                          textInputAction: TextInputAction.done,
                          onSubmitted: (_) => _login(),
                          decoration: InputDecoration(
                            hintText: '面板密码',
                            prefixIcon: const Icon(Icons.lock_outline),
                            suffixIcon: IconButton(
                              icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                              onPressed: () => setState(() => obscure = !obscure),
                            ),
                          ),
                        ),
                        const SizedBox(height: 18),
                        FilledButton(
                          onPressed: busy ? null : _login,
                          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
                          child: busy
                              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                              : const Text('进入面板'),
                        ),
                        if (error != null) ...[
                          const SizedBox(height: 12),
                          Text(
                            error!,
                            textAlign: TextAlign.center,
                            style: TextStyle(color: cs.error),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  '账号密码见服务器 /opt/astrbot/deploy_info.txt\n登录过程使用 RSA + AES-GCM 端到端加密',
                  textAlign: TextAlign.center,
                  style: tt.bodySmall?.copyWith(color: cs.onSurfaceVariant, height: 1.6),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
