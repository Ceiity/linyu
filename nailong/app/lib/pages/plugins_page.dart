import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../core/agent_api.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';
import 'home_shell.dart';

class PluginsPage extends StatefulWidget {
  final bool active;
  final void Function(String target) onOpenLogs;

  const PluginsPage({super.key, required this.active, required this.onOpenLogs});

  @override
  State<PluginsPage> createState() => _PluginsPageState();
}

class _PluginsPageState extends State<PluginsPage> {
  List<Map<String, dynamic>>? plugins;
  String? error;
  String query = '';
  final pending = <String>{};
  bool loadedOnce = false;

  @override
  void didUpdateWidget(PluginsPage old) {
    super.didUpdateWidget(old);
    if (widget.active && !loadedOnce) _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (widget.active && !loadedOnce && ConnScope.of(context).api != null) _load();
  }

  AgentApi? get api => ConnScope.maybeOf(context)?.api;

  Future<void> _load() async {
    final a = api;
    if (a == null) return;
    loadedOnce = true;
    try {
      final rows = (await a.get('/api/plugins') as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
      if (mounted) {
        setState(() {
          plugins = rows;
          error = null;
        });
      }
    } catch (e) {
      loadedOnce = false;
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _toggle(Map<String, dynamic> p, bool on) async {
    final name = p['name'] as String;
    setState(() => pending.add(name));
    await runAction(
      context,
      () => api!.post('/api/plugins/$name/${on ? 'enable' : 'disable'}'),
      success: on ? '已启用' : '已禁用',
    );
    if (mounted) setState(() => pending.remove(name));
    _load();
  }

  Future<void> _installGithub() async {
    final repo = TextEditingController(text: 'https://github.com/');
    final ref = TextEditingController();
    final sha = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('从 GitHub 安装'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: repo,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(labelText: '仓库地址'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: ref,
                decoration: const InputDecoration(labelText: '版本（标签/分支/提交，可选）'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: sha,
                decoration: const InputDecoration(labelText: 'SHA-256（可选，填写则强制校验）'),
              ),
              const SizedBox(height: 12),
              Text(
                '会使用「下载加速」里你配置的可信 GitHub 下载源，自动测速、断点续传、失败切换，并把版本固定到具体提交。',
                style: TextStyle(fontSize: 12, color: Theme.of(d).colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('安装')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final r = await runTask(
      context,
      api!,
      () => api!.post('/api/plugins/install', {
        'repo': repo.text.trim(),
        if (ref.text.trim().isNotEmpty) 'ref': ref.text.trim(),
        if (sha.text.trim().isNotEmpty) 'sha256': sha.text.trim(),
      }),
    );
    if (r != null && r['status'] == 'success' && mounted) {
      final res = Map<String, dynamic>.from(r['result'] as Map);
      toast(
        context,
        '安装完成 · 来源 ${res['source']} · ${res['pinned'] == true ? '提交 ${res['commit'].toString().substring(0, 8)}' : '未能固定提交'}',
      );
    }
    _load();
  }

  Future<void> _installZip() async {
    final f = (await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['zip'])).firstOrNull;
    if (f == null || !mounted) return;
    final size = await f.length() ?? (await f.readAsBytes()).length;
    if (!mounted) return;
    await runTask(context, api!, () => api!.upload('/api/plugins/upload', f.name, f.readAsByteStream(), size));
    _load();
  }

  void _detail(Map<String, dynamic> p) {
    final cs = Theme.of(context).colorScheme;
    final name = p['name'] as String;
    showModalBottomSheet(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (c) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              title: Text(
                p['display_name']?.toString() ?? name,
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
              ),
              subtitle: Text(
                '${p['author']} · v${p['version']}${p['repo'].toString().isEmpty ? '' : '\n${p['repo']}'}',
              ),
              isThreeLine: p['repo'].toString().isNotEmpty,
            ),
            if (p['desc'].toString().isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text(p['desc'].toString(), style: TextStyle(color: cs.onSurfaceVariant)),
              ),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.tune),
              title: const Text('插件配置'),
              onTap: () {
                Navigator.pop(c);
                pushPage(context, PluginConfigPage(name: name));
              },
            ),
            ListTile(
              leading: const Icon(Icons.receipt_long_outlined),
              title: const Text('插件日志'),
              onTap: () {
                Navigator.pop(c);
                pushPage(context, PluginLogPage(name: name));
              },
            ),
            if (!(p['reserved'] == true))
              ListTile(
                leading: const Icon(Icons.system_update_alt),
                title: Text(p['has_update'] == true ? '更新到 ${p['online_version']}' : '更新'),
                onTap: () async {
                  Navigator.pop(c);
                  await runTask(context, api!, () => api!.post('/api/plugins/$name/update'));
                  _load();
                },
              ),
            if (!(p['reserved'] == true))
              ListTile(
                leading: Icon(Icons.delete_outline, color: cs.error),
                title: Text('卸载', style: TextStyle(color: cs.error)),
                onTap: () async {
                  Navigator.pop(c);
                  await _uninstall(name);
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _uninstall(String name) async {
    var delConfig = false;
    var delData = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: Text('卸载 $name？'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CheckboxListTile(
                value: delConfig,
                onChanged: (v) => set(() => delConfig = v ?? false),
                title: const Text('同时删除插件配置'),
                contentPadding: EdgeInsets.zero,
              ),
              CheckboxListTile(
                value: delData,
                onChanged: (v) => set(() => delData = v ?? false),
                title: const Text('同时删除插件数据'),
                contentPadding: EdgeInsets.zero,
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('取消')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(d).colorScheme.error),
              onPressed: () => Navigator.pop(d, true),
              child: const Text('卸载'),
            ),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    await runAction(
      context,
      () => api!.post('/api/plugins/$name/uninstall', {'delete_config': delConfig, 'delete_data': delData}),
      success: '已卸载',
    );
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final list = (plugins ?? [])
        .where(
          (p) =>
              query.isEmpty ||
              '${p['name']} ${p['display_name']} ${p['desc']}'.toLowerCase().contains(query.toLowerCase()),
        )
        .toList();
    return Scaffold(
      floatingActionButton: api == null
          ? null
          : FloatingActionButton.extended(
              onPressed: () => showModalBottomSheet(
                context: context,
                builder: (c) => SafeArea(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      ListTile(
                        leading: const Icon(Icons.code),
                        title: const Text('从 GitHub 安装'),
                        subtitle: const Text('支持下载加速与 SHA-256 校验'),
                        onTap: () {
                          Navigator.pop(c);
                          _installGithub();
                        },
                      ),
                      ListTile(
                        leading: const Icon(Icons.folder_zip_outlined),
                        title: const Text('上传本地 ZIP'),
                        onTap: () {
                          Navigator.pop(c);
                          _installZip();
                        },
                      ),
                    ],
                  ),
                ),
              ),
              icon: const Icon(Icons.add),
              label: const Text('安装插件'),
            ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: CustomScrollView(
          slivers: [
            const SliverAppBar.large(title: Text('插件')),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: TextField(
                  onChanged: (v) => setState(() => query = v),
                  decoration: const InputDecoration(isDense: true, hintText: '搜索插件', prefixIcon: Icon(Icons.search)),
                ),
              ),
            ),
            if (plugins == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error != null
                    ? MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: _load)
                    : offlinePlaceholder(context),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
                sliver: SliverList.separated(
                  itemCount: list.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (_, i) {
                    final p = list[i];
                    final name = p['name'] as String;
                    return InfoCard(
                      onTap: () => _detail(p),
                      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
                      child: Row(
                        children: [
                          CircleAvatar(
                            backgroundColor: p['activated'] == true ? cs.primaryContainer : cs.surfaceContainerHighest,
                            child: Icon(
                              Icons.extension,
                              color: p['activated'] == true ? cs.onPrimaryContainer : cs.outline,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Flexible(
                                      child: Text(
                                        p['display_name']?.toString() ?? name,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(fontWeight: FontWeight.w700),
                                      ),
                                    ),
                                    if (p['has_update'] == true) ...[
                                      const SizedBox(width: 6),
                                      const StatusChip('可更新', Tone.info, dot: false),
                                    ],
                                    if (p['reserved'] == true) ...[
                                      const SizedBox(width: 6),
                                      const StatusChip('内置', Tone.idle, dot: false),
                                    ],
                                  ],
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  p['desc']?.toString() ?? '',
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontSize: 12.5, color: cs.onSurfaceVariant),
                                ),
                              ],
                            ),
                          ),
                          pending.contains(name)
                              ? const Padding(
                                  padding: EdgeInsets.all(14),
                                  child: SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  ),
                                )
                              : Switch(
                                  value: p['activated'] == true,
                                  onChanged: p['reserved'] == true ? null : (v) => _toggle(p, v),
                                ),
                        ],
                      ),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class PluginConfigPage extends StatefulWidget {
  final String name;

  const PluginConfigPage({super.key, required this.name});

  @override
  State<PluginConfigPage> createState() => _PluginConfigPageState();
}

class _PluginConfigPageState extends State<PluginConfigPage> {
  final ctrl = TextEditingController();
  String? error;
  bool loading = true;
  bool hasConfig = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    try {
      final d = await ConnScope.of(context).api!.get('/api/plugins/${widget.name}/config');
      final cfg = d is Map && d['config'] is Map ? d['config'] : d;
      setState(() {
        hasConfig = cfg is Map && cfg.isNotEmpty;
        ctrl.text = const JsonEncoder.withIndent('  ').convert(cfg);
        loading = false;
      });
    } catch (e) {
      setState(() {
        error = e.toString();
        loading = false;
      });
    }
  }

  Future<void> _save() async {
    Object? parsed;
    try {
      parsed = jsonDecode(ctrl.text);
    } catch (_) {
      return toast(context, 'JSON 格式不正确');
    }
    if (parsed is! Map) return toast(context, '配置必须是 JSON 对象');
    await runAction(
      context,
      () => ConnScope.of(context).api!.put('/api/plugins/${widget.name}/config', parsed),
      success: '已保存',
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('${widget.name} 配置'),
        actions: [IconButton(onPressed: loading ? null : _save, icon: const Icon(Icons.save_outlined))],
      ),
      body: loading
          ? const LoadingView()
          : error != null
          ? MessageView(icon: Icons.error_outline, text: error!)
          : !hasConfig
          ? const MessageView(icon: Icons.tune, text: '该插件没有可配置项')
          : Padding(
              padding: const EdgeInsets.all(16),
              child: TextField(
                controller: ctrl,
                maxLines: null,
                expands: true,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5),
                decoration: const InputDecoration(alignLabelWithHint: true),
              ),
            ),
    );
  }
}

class PluginLogPage extends StatefulWidget {
  final String name;

  const PluginLogPage({super.key, required this.name});

  @override
  State<PluginLogPage> createState() => _PluginLogPageState();
}

class _PluginLogPageState extends State<PluginLogPage> {
  List<Map<String, dynamic>>? lines;
  String? error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        final r = await ConnScope.of(context).api!.get('/api/plugins/${widget.name}/logs');
        setState(() => lines = (r as List).map((e) => Map<String, dynamic>.from(e as Map)).toList());
      } catch (e) {
        setState(() => error = e.toString());
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text('${widget.name} 日志')),
      body: lines == null
          ? (error == null ? const LoadingView() : MessageView(icon: Icons.error_outline, text: error!))
          : lines!.isEmpty
          ? const MessageView(icon: Icons.receipt_long_outlined, text: '最近日志里没有这个插件的记录')
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: lines!.length,
              itemBuilder: (_, i) => SelectableText(
                '${lines![i]['time']} ${lines![i]['text']}',
                style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11.5,
                  height: 1.45,
                  color: lines![i]['level'] == 'ERROR' ? cs.error : null,
                ),
              ),
            ),
    );
  }
}
