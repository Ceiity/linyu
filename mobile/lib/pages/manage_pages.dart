import 'package:material_ui/material_ui.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../ui/widgets.dart';

/// 通用加载页：大标题 + 下拉刷新 + 错误重试。
class LoaderPage extends StatefulWidget {
  final String title;
  final Future<dynamic> Function(ApiClient api) load;
  final List<Widget> Function(BuildContext context, dynamic data, ApiClient api, VoidCallback reload) builder;
  final List<Widget> Function(BuildContext context, ApiClient api, VoidCallback reload)? actions;

  const LoaderPage({super.key, required this.title, required this.load, required this.builder, this.actions});

  @override
  State<LoaderPage> createState() => _LoaderPageState();
}

class _LoaderPageState extends State<LoaderPage> {
  dynamic data;
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    final api = AppScope.read(context).api;
    if (api == null) return;
    setState(() => loading = data == null);
    try {
      final d = await widget.load(api);
      if (mounted) {
        setState(() {
          data = d;
          error = null;
          loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = AppScope.of(context).api;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _reload,
        child: CustomScrollView(
          slivers: [
            SliverAppBar.large(
              title: Text(widget.title),
              actions: api == null || widget.actions == null ? null : widget.actions!(context, api, _reload),
            ),
            if (api == null || loading)
              const SliverFillRemaining(hasScrollBody: false, child: LoadingView())
            else if (data == null)
              SliverFillRemaining(
                hasScrollBody: false,
                child: MessageView(icon: Icons.cloud_off, text: error ?? '加载失败', actionText: '重试', onAction: _reload),
              )
            else
              SliverList.list(children: [...widget.builder(context, data, api, _reload), const SizedBox(height: 32)]),
          ],
        ),
      ),
    );
  }
}

Widget _kvTile(BuildContext context, String k, String? v) {
  final cs = Theme.of(context).colorScheme;
  final value = (v == null || v.isEmpty) ? '-' : v;
  return ListTile(
    title: Text(k, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
    subtitle: Text(
      value,
      style: TextStyle(color: cs.onSurface, fontSize: 15, fontWeight: FontWeight.w600),
    ),
    trailing: value == '-' ? null : Icon(Icons.copy_rounded, size: 18, color: cs.outline),
    onTap: value == '-' ? null : () => copyText(context, value, label: k),
  );
}

// ---------- AstrBot ----------

class AstrbotPage extends StatelessWidget {
  const AstrbotPage({super.key});

  @override
  Widget build(BuildContext context) {
    return LoaderPage(
      title: 'AstrBot',
      load: (api) async {
        final a = await api.get('/api/astrbot');
        dynamic p;
        try {
          p = await api.get('/api/plugins/astrbot');
        } catch (_) {}
        return {'a': a, 'p': p};
      },
      builder: (context, d, api, reload) {
        final a = Map<String, dynamic>.from(d['a'] as Map);
        final st = Map<String, dynamic>.from(a['status'] ?? {});
        final plugins = ((d['p']?['plugins'] ?? []) as List);
        final running = st['running'] == true;
        Future<void> act(String action) async {
          if (action != 'start' &&
              !await confirmDialog(
                context,
                title: action == 'stop' ? '确认停止 AstrBot？' : '确认重启 AstrBot？',
                destructive: action == 'stop',
              )) {
            return;
          }
          if (!context.mounted) return;
          await runAction(
            context,
            () => api.post('/api/astrbot/action', {'action': action}, const Duration(seconds: 130)),
            success: '操作已执行',
          );
          reload();
        }

        return [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: InfoCard(
              icon: Icons.smart_toy_outlined,
              title: '主服务',
              actions: [StatusChip(containerStatusText(st['status']), containerTone(st['status']))],
              child: Row(
                children: [
                  Expanded(
                    child: running
                        ? OutlinedButton.icon(
                            onPressed: () => act('stop'),
                            icon: const Icon(Icons.stop_rounded),
                            label: const Text('停止'),
                          )
                        : FilledButton.icon(
                            onPressed: () => act('start'),
                            icon: const Icon(Icons.play_arrow_rounded),
                            label: const Text('启动'),
                          ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.tonalIcon(
                      onPressed: () => act('restart'),
                      icon: const Icon(Icons.restart_alt_rounded),
                      label: const Text('重启'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SectionTitle('登录信息'),
          GroupCard(
            children: [
              _kvTile(context, 'WebUI 地址', a['url']?.toString()),
              _kvTile(context, '账号', a['username']?.toString()),
              _kvTile(context, '初始密码', a['password']?.toString()),
              _kvTile(context, '连接 Token', a['token']?.toString()),
            ],
          ),
          const SectionTitle('维护'),
          GroupCard(
            children: [
              ListTile(
                leading: const Icon(Icons.alternate_email),
                title: const Text('应用免 @ / 免前缀'),
                subtitle: const Text('群聊无需 @ 和前缀即可唤醒，会重启 AstrBot'),
                onTap: () => startTask(context, api, '/api/astrbot/no-prefix'),
              ),
              ListTile(
                leading: const Icon(Icons.auto_fix_high),
                title: const Text('一键配置连接'),
                subtitle: const Text('同步 NapCat 反向 WebSocket、Token 与网络'),
                onTap: () => startTask(context, api, '/api/connection/repair'),
              ),
            ],
          ),
          SectionTitle('插件 ${plugins.length}'),
          GroupCard(
            children: [
              if (plugins.isEmpty) const ListTile(title: Text('暂无插件')),
              for (final p in plugins)
                ListTile(
                  leading: Icon(p['is_dir'] == true ? Icons.extension_outlined : Icons.insert_drive_file_outlined),
                  title: Text(p['name'].toString()),
                  subtitle: Text(p['mtime']?.toString() ?? ''),
                ),
            ],
          ),
        ];
      },
    );
  }
}

// ---------- 任务 ----------

class TasksPage extends StatelessWidget {
  const TasksPage({super.key});

  @override
  Widget build(BuildContext context) {
    return LoaderPage(
      title: '任务记录',
      load: (api) => api.get('/api/tasks'),
      builder: (context, d, api, reload) {
        final tasks = (d as List).reversed.toList();
        if (tasks.isEmpty) return [const SizedBox(height: 120), const MessageView(icon: Icons.task_alt, text: '暂无任务')];
        return [
          GroupCard(
            children: [
              for (final t in tasks)
                ListTile(
                  leading: SizedBox(
                    width: 36,
                    height: 36,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        CircularProgressIndicator(
                          value: t['status'] == 'failed' ? 1 : ((t['progress'] ?? 0) as num) / 100,
                          strokeWidth: 3,
                          color: toneColor(Theme.of(context).colorScheme, taskTone(t['status'])),
                        ),
                      ],
                    ),
                  ),
                  title: Text(t['title'].toString()),
                  subtitle: Text(t['updated_at']?.toString() ?? ''),
                  trailing: StatusChip(taskStatusText(t['status']), taskTone(t['status'])),
                  onTap: () async {
                    await showTaskSheet(context, api, t['id'].toString());
                    reload();
                  },
                ),
            ],
          ),
        ];
      },
    );
  }
}

// ---------- 备份 ----------

class BackupPage extends StatelessWidget {
  const BackupPage({super.key});

  @override
  Widget build(BuildContext context) {
    return LoaderPage(
      title: '备份恢复',
      load: (api) => api.get('/api/backups'),
      actions: (context, api, reload) => [
        Padding(
          padding: const EdgeInsets.only(right: 12),
          child: FilledButton.tonalIcon(
            icon: const Icon(Icons.backup_outlined),
            label: const Text('立即备份'),
            onPressed: () async {
              await startTask(context, api, '/api/backup/create');
              reload();
            },
          ),
        ),
      ],
      builder: (context, d, api, reload) {
        final rows = d as List;
        if (rows.isEmpty) {
          return [const SizedBox(height: 120), const MessageView(icon: Icons.archive_outlined, text: '暂无备份')];
        }
        return [
          GroupCard(
            children: [
              for (final b in rows)
                ListTile(
                  leading: const Icon(Icons.inventory_2_outlined),
                  title: Text(b['name'].toString(), maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${fmtBytes(b['size'] as num?)} · ${b['mtime']}'),
                  trailing: TextButton(
                    style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                    onPressed: () async {
                      final ok = await typeConfirmDialog(
                        context,
                        title: '恢复备份',
                        message: '将用 ${b['name']} 覆盖当前数据。需先在面板设置开启“危险操作”。',
                        word: 'RESTORE',
                      );
                      if (!ok || !context.mounted) return;
                      await startTask(context, api, '/api/backup/restore', {'file': b['name'], 'confirm': 'RESTORE'});
                      reload();
                    },
                    child: const Text('恢复'),
                  ),
                ),
            ],
          ),
        ];
      },
    );
  }
}

// ---------- 更新 ----------

class UpdatePage extends StatelessWidget {
  const UpdatePage({super.key});

  @override
  Widget build(BuildContext context) {
    return LoaderPage(
      title: '更新中心',
      load: (api) => api.get('/api/dashboard'),
      builder: (context, d, api, reload) {
        Future<void> upd(String target, String name) async {
          if (!await confirmDialog(context, title: '更新$name？', message: '会拉取最新镜像并重建容器，保留现有配置。')) return;
          if (!context.mounted) return;
          await startTask(context, api, '/api/update', {'target': target});
        }

        final containers = (d['docker']?['containers'] ?? '').toString().split('\n').where((l) => l.trim().isNotEmpty);
        return [
          GroupCard(
            children: [
              ListTile(
                leading: const Icon(Icons.smart_toy_outlined),
                title: const Text('更新 AstrBot'),
                trailing: const Icon(Icons.download_rounded),
                onTap: () => upd('astrbot', ' AstrBot'),
              ),
              ListTile(
                leading: const Icon(Icons.hub_outlined),
                title: const Text('更新机器人 (NapCat)'),
                trailing: const Icon(Icons.download_rounded),
                onTap: () => upd('napcat', '机器人'),
              ),
              ListTile(
                leading: const Icon(Icons.system_update_alt),
                title: const Text('全部更新'),
                trailing: const Icon(Icons.download_rounded),
                onTap: () => upd('all', '全部组件'),
              ),
            ],
          ),
          const SectionTitle('当前容器'),
          GroupCard(
            children: [
              for (final l in containers)
                Builder(
                  builder: (context) {
                    final p = l.split('\t');
                    return ListTile(
                      title: Text(p[0]),
                      subtitle: Text([if (p.length > 1) p[1], if (p.length > 2) p[2]].join('\n')),
                      isThreeLine: p.length > 2,
                    );
                  },
                ),
            ],
          ),
        ];
      },
    );
  }
}
