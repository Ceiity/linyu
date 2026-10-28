import 'package:material_ui/material_ui.dart';

import '../core/store.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';

/// 下载加速：GitHub 下载源、Docker 镜像加速器、PyPI 镜像、Docker 软件源。
/// 全部由用户自行添加，默认只有官方源；只接受 HTTPS。
class SourcesPage extends StatefulWidget {
  const SourcesPage({super.key});

  @override
  State<SourcesPage> createState() => _SourcesPageState();
}

class _SourcesPageState extends State<SourcesPage> {
  late SourceSettings s;
  List<Map<String, dynamic>>? ghTest;
  bool testing = false;
  bool dirty = false;

  @override
  void initState() {
    super.initState();
    final cur = StoreScope.read(context).sources;
    s = SourceSettings(
      github: [...cur.github.map((e) => Map<String, dynamic>.from(e))],
      registries: [...cur.registries],
      pypi: [...cur.pypi],
      dockerApt: [...cur.dockerApt],
    );
    WidgetsBinding.instance.addPostFrameCallback((_) => _pull());
  }

  /// 已连接时以服务器上的配置为准。
  Future<void> _pull() async {
    final api = ConnScope.maybeOf(context)?.api;
    if (api == null) return;
    try {
      final d = Map<String, dynamic>.from(await api.get('/api/sources') as Map);
      if (!mounted || dirty) return;
      setState(() {
        s = SourceSettings(
          github: ((d['github'] ?? []) as List)
              .map((e) => Map<String, dynamic>.from(e as Map))
              .where((e) => e['id'] != 'official')
              .toList(),
          registries: ((d['registries'] ?? []) as List).map((e) => e.toString()).toList(),
          pypi: ((d['pypi'] ?? []) as List)
              .map((e) => e.toString())
              .where((e) => e != 'https://pypi.org/simple')
              .toList(),
          dockerApt: ((d['docker_apt'] ?? []) as List)
              .map((e) => e.toString())
              .where((e) => e != 'https://download.docker.com')
              .toList(),
        );
      });
    } catch (_) {}
  }

  Future<void> _save() async {
    final store = StoreScope.read(context);
    final api = ConnScope.maybeOf(context)?.api;
    if (api != null) {
      final ok = await runAction(context, () => api.put('/api/sources', s.toJson()));
      if (ok == null) return;
    }
    await store.setSources(s);
    if (!mounted) return;
    setState(() => dirty = false);
    toast(context, api == null ? '已保存，部署时生效' : '已保存到服务器');
  }

  Future<void> _testGithub() async {
    final api = ConnScope.maybeOf(context)?.api;
    if (api == null) return toast(context, '连接服务器后才能在服务器上测速');
    if (dirty) await _save();
    if (!mounted) return;
    setState(() => testing = true);
    final r = await runAction(context, () => api.post('/api/sources/github/test', null, const Duration(minutes: 3)));
    if (!mounted) return;
    setState(() {
      testing = false;
      if (r is List) ghTest = r.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    });
  }

  Future<String?> _ask(String title, String hint, {String? initial}) async {
    final c = TextEditingController(text: initial ?? 'https://');
    return showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(title),
        content: TextField(
          controller: c,
          autofocus: true,
          keyboardType: TextInputType.url,
          decoration: InputDecoration(hintText: hint),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(d, c.text.trim()), child: const Text('添加')),
        ],
      ),
    );
  }

  bool _https(String u) => RegExp(r'^https://[A-Za-z0-9.\-]+(:\d+)?(/\S*)?$').hasMatch(u);

  Future<void> _addGithub() async {
    String type = 'prefix';
    final url = TextEditingController(text: 'https://');
    final name = TextEditingController();
    final r = await showDialog<bool>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: const Text('添加 GitHub 下载源'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'prefix', label: Text('前缀代理')),
                  ButtonSegment(value: 'replace', label: Text('替换域名')),
                ],
                selected: {type},
                onSelectionChanged: (v) => set(() => type = v.first),
              ),
              const SizedBox(height: 8),
              Text(
                type == 'prefix' ? '下载地址 = 该地址 + 原始 GitHub 地址' : '把 https://github.com 替换成该地址',
                style: TextStyle(fontSize: 12, color: Theme.of(d).colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: '名称（可选）'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: url,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(labelText: 'HTTPS 地址'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('添加')),
          ],
        ),
      ),
    );
    if (r != true || !mounted) return;
    if (!_https(url.text.trim())) return toast(context, '只接受 HTTPS 地址');
    final host = Uri.parse(url.text.trim()).host;
    setState(() {
      s.github = [
        ...s.github,
        {
          'id': host.replaceAll('.', '-'),
          'name': name.text.trim().isEmpty ? host : name.text.trim(),
          'type': type,
          'url': url.text.trim(),
          'enabled': true,
        },
      ];
      dirty = true;
    });
  }

  Future<void> _addTo(List<String> list, String title, String hint, {bool registry = false}) async {
    final v = await _ask(title, hint);
    if (v == null || v.isEmpty || !mounted) return;
    if (!_https(v)) return toast(context, '只接受 HTTPS 地址');
    setState(() {
      list.add(
        registry ? v.replaceFirst('https://', '').replaceAll(RegExp(r'/$'), '') : v.replaceAll(RegExp(r'/$'), ''),
      );
      dirty = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final connected = ConnScope.maybeOf(context)?.api != null;
    Widget urlTile(String v, List<String> list, {String? sub}) => ListTile(
      title: Text(v, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: sub == null ? null : Text(sub),
      trailing: IconButton(
        icon: const Icon(Icons.delete_outline),
        onPressed: () => setState(() {
          list.remove(v);
          dirty = true;
        }),
      ),
    );
    Widget official(String text) => ListTile(
      leading: Icon(Icons.verified, color: cs.success),
      title: Text(text),
      subtitle: const Text('官方源 · 始终作为兜底'),
    );
    return Scaffold(
      floatingActionButton: dirty
          ? FloatingActionButton.extended(
              onPressed: _save,
              icon: const Icon(Icons.save_outlined),
              label: const Text('保存'),
            )
          : null,
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('下载加速')),
          SliverList.list(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Text(
                  '奶龙不内置任何第三方镜像站。你添加的来源只在测速可用时才会使用；无论从哪下载，'
                  'Docker 镜像都按固定摘要校验，Docker 软件包按官方 GPG 签名校验，Agent 依赖按哈希校验，GitHub 插件包校验 ZIP 结构与 SHA-256。',
                  style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13, height: 1.6),
                ),
              ),
              SectionTitle(
                'GitHub 下载源（插件安装）',
                trailing: TextButton.icon(
                  onPressed: testing ? null : _testGithub,
                  icon: testing
                      ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.speed, size: 18),
                  label: Text(connected ? '测速' : '连接后可测速'),
                ),
              ),
              GroupCard(
                children: [
                  official('https://github.com'),
                  for (final g in s.github)
                    SwitchListTile(
                      title: Text('${g['name']}'),
                      subtitle: Text(
                        '${g['type'] == 'prefix' ? '前缀代理' : '替换域名'} · ${g['url']}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      value: g['enabled'] != false,
                      onChanged: (v) => setState(() {
                        g['enabled'] = v;
                        dirty = true;
                      }),
                      secondary: IconButton(
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () => setState(() {
                          s.github = s.github.where((e) => e != g).toList();
                          dirty = true;
                        }),
                      ),
                    ),
                  ListTile(leading: const Icon(Icons.add), title: const Text('添加 GitHub 下载源'), onTap: _addGithub),
                ],
              ),
              if (ghTest != null) ...[
                const SectionTitle('测速结果（服务器实测，缓存 6 小时）'),
                GroupCard(
                  children: [
                    for (final t in ghTest!)
                      ListTile(
                        leading: Icon(
                          t['ok'] == true ? Icons.check_circle : Icons.cancel,
                          color: t['ok'] == true ? cs.success : cs.error,
                        ),
                        title: Text('${t['name']}'),
                        subtitle: Text(
                          t['ok'] == true
                              ? '延迟 ${t['latency_ms']} ms · ${fmtSpeed(t['speed_bps'] as num?)} · ${t['resume'] == true ? '支持断点续传' : '不支持续传'}'
                              : '${t['error']}',
                        ),
                      ),
                  ],
                ),
              ],
              const SectionTitle('Docker 镜像加速器'),
              GroupCard(
                children: [
                  official('Docker Hub（registry-1.docker.io）'),
                  for (final r in [...s.registries]) urlTile(r, s.registries, sub: '部署时自动测速：可达性、摘要存在、架构、TLS'),
                  ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('添加镜像加速器'),
                    onTap: () => _addTo(s.registries, '镜像加速器地址', 'https://your-mirror.example.com', registry: true),
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
                child: Text(
                  '奶龙使用“从加速器按摘要拉取后打标签”的方式，不修改 Docker 守护进程配置，也不重启 Docker，不影响服务器上的其它容器。',
                  style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12),
                ),
              ),
              const SectionTitle('PyPI 镜像（Agent 依赖）'),
              GroupCard(
                children: [
                  official('https://pypi.org/simple'),
                  for (final r in [...s.pypi]) urlTile(r, s.pypi),
                  ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('添加 PyPI 镜像'),
                    onTap: () => _addTo(s.pypi, 'PyPI 简单索引地址', 'https://pypi.example.com/simple'),
                  ),
                ],
              ),
              const SectionTitle('Docker 软件源（安装 Docker）'),
              GroupCard(
                children: [
                  official('https://download.docker.com'),
                  for (final r in [...s.dockerApt]) urlTile(r, s.dockerApt),
                  ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('添加 Docker 软件源镜像'),
                    onTap: () => _addTo(s.dockerApt, 'Docker CE 镜像地址', 'https://mirror.example.com/docker-ce'),
                  ),
                ],
              ),
              const SizedBox(height: 100),
            ],
          ),
        ],
      ),
    );
  }
}
