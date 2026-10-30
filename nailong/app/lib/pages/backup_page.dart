import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../core/agent_api.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';

class BackupPage extends StatefulWidget {
  const BackupPage({super.key});

  @override
  State<BackupPage> createState() => _BackupPageState();
}

class _BackupPageState extends State<BackupPage> {
  Map<String, dynamic>? data;
  String? error;

  AgentApi? get api => ConnScope.maybeOf(context)?.api;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    if (api == null) return setState(() => error = '未连接服务器');
    try {
      final d = Map<String, dynamic>.from(await api!.get('/api/backups') as Map);
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

  Future<void> _create() async {
    final scopes = Map<String, dynamic>.from(data!['scopes'] as Map);
    final chosen = scopes.keys.toSet();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: const Text('创建备份'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final e in scopes.entries)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: chosen.contains(e.key),
                  title: Text(e.value.toString()),
                  onChanged: (v) => set(() => v == true ? chosen.add(e.key) : chosen.remove(e.key)),
                ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('取消')),
            FilledButton(onPressed: chosen.isEmpty ? null : () => Navigator.pop(d, true), child: const Text('开始备份')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    await runTask(context, api!, () => api!.post('/api/backups', {'scopes': chosen.toList()}));
    _load();
  }

  Future<void> _download(Map<String, dynamic> b) async {
    final name = b['name'] as String;
    toast(context, '正在下载 ${fmtBytes(b['size'] as num?)}…');
    try {
      final bytes = await api!.download('/api/backups/$name/download');
      final path = await FilePicker.saveFile(fileName: name, bytes: bytes, mimeType: 'application/gzip');
      if (mounted && path != null) toast(context, '已保存到手机');
    } catch (e) {
      if (mounted) toast(context, e.toString());
    }
  }

  Future<void> _upload() async {
    final f = (await FilePicker.pickFiles()).firstOrNull;
    if (f == null || !mounted) return;
    if (!f.name.endsWith('.tar.gz')) return toast(context, '请选择奶龙备份文件（.tar.gz）');
    final size = await f.length() ?? (await f.readAsBytes()).length;
    if (!mounted) return;
    toast(context, '正在上传并校验…');
    await runAction(
      context,
      () => api!.upload('/api/backups/upload', f.name, f.readAsByteStream(), size),
      success: '上传成功，已通过完整性校验',
    );
    _load();
  }

  Future<void> _restore(Map<String, dynamic> b) async {
    final name = b['name'] as String;
    final verified = await runAction(context, () => api!.post('/api/backups/$name/verify'));
    if (verified == null || !mounted) return;
    final scopes = (verified['scopes'] as List).map((e) => (data!['scopes'] as Map)[e] ?? e).join('、');
    final ok = await typeConfirmDialog(
      context,
      title: '恢复备份',
      message:
          '完整性校验通过（${verified['files']} 个文件：$scopes）。\n\n恢复会先自动备份当前数据，然后停止 AstrBot / NapCat，'
          '覆盖对应文件后再启动。',
      word: name,
    );
    if (!ok || !mounted) return;
    final t = await runTask(context, api!, () => api!.post('/api/backups/$name/restore', {'confirm': name}));
    if (t?['status'] == 'success' && mounted) {
      toast(context, '已恢复 ${t!['result']['restored']} 个文件，恢复前备份：${t['result']['safety_backup']}');
    }
    _load();
  }

  Future<void> _delete(Map<String, dynamic> b) async {
    if (!await confirmDialog(
      context,
      title: '删除备份？',
      message: b['name'].toString(),
      destructive: true,
      confirmText: '删除',
    )) {
      return;
    }
    if (!mounted) return;
    await runAction(context, () => api!.delete('/api/backups/${b['name']}'), success: '已删除');
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final items = ((data?['items'] ?? []) as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    return Scaffold(
      floatingActionButton: data == null
          ? null
          : FloatingActionButton.extended(
              onPressed: _create,
              icon: const Icon(Icons.backup_outlined),
              label: const Text('立即备份'),
            ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: CustomScrollView(
          slivers: [
            SliverAppBar(
              pinned: true,
              title: const Text('备份恢复'),
              actions: [
                IconButton(
                  tooltip: '上传备份',
                  onPressed: data == null ? null : _upload,
                  icon: const Icon(Icons.upload_file),
                ),
              ],
            ),
            if (data == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: error == null
                    ? const LoadingView()
                    : MessageView(icon: Icons.error_outline, text: error!, actionText: '重试', onAction: _load),
              )
            else if (items.isEmpty)
              const SliverFillRemaining(
                hasScrollBody: false,
                child: MessageView(icon: Icons.archive_outlined, text: '还没有备份'),
              )
            else
              SliverList.list(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: Text(
                      '备份包含逐文件 SHA-256 清单，恢复前会完整校验。',
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13),
                    ),
                  ),
                  GroupCard(
                    children: [
                      for (final b in items)
                        ListTile(
                          leading: const Icon(Icons.inventory_2_outlined),
                          title: Text(b['name'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle: Text(
                            '${fmtBytes(b['size'] as num?)} · ${DateTime.fromMillisecondsSinceEpoch((b['mtime'] as int) * 1000).toString().substring(0, 16)}',
                          ),
                          trailing: PopupMenuButton<String>(
                            onSelected: (v) => switch (v) {
                              'download' => _download(b),
                              'restore' => _restore(b),
                              _ => _delete(b),
                            },
                            itemBuilder: (_) => [
                              const PopupMenuItem(value: 'download', child: Text('下载到手机')),
                              const PopupMenuItem(value: 'restore', child: Text('恢复')),
                              PopupMenuItem(
                                value: 'delete',
                                child: Text('删除', style: TextStyle(color: cs.error)),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 96),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
