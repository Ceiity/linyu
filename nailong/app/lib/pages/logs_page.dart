import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';

import '../core/connection.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';
import 'conn_scope.dart';

class LogsPage extends StatefulWidget {
  final bool active;
  final ValueNotifier<String?> target;

  const LogsPage({super.key, required this.active, required this.target});

  @override
  State<LogsPage> createState() => _LogsPageState();
}

const _levels = ['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'];

class _LogsPageState extends State<LogsPage> {
  String target = 'astrbot';
  List<String> targets = ['astrbot', 'agent'];
  final lines = <Map<String, dynamic>>[];
  String level = 'ALL';
  String query = '';
  bool paused = false;
  bool follow = true;
  bool raw = false;
  String? error;
  StreamSubscription? sub;
  ServerConnection? conn;
  final buffered = <Map<String, dynamic>>[];
  final scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    widget.target.addListener(_onTarget);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final c = ConnScope.of(context);
    if (c != conn) {
      conn?.removeListener(_onConn);
      conn = c..addListener(_onConn);
    }
    _sync();
  }

  @override
  void didUpdateWidget(LogsPage old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _onConn() => _sync();

  void _onTarget() {
    final t = widget.target.value;
    if (t == null) return;
    widget.target.value = null;
    if (!targets.contains(t)) targets = [...targets, t];
    _switch(t);
  }

  /// 只在页面可见且已连接时保持 WebSocket。
  void _sync() {
    if (!mounted) return;
    final online = conn?.api != null;
    if (widget.active && online && sub == null) {
      _loadTargets();
      _open();
    } else if ((!widget.active || !online) && sub != null) {
      sub?.cancel();
      sub = null;
    }
  }

  Future<void> _loadTargets() async {
    try {
      final rows = await conn!.api!.get('/api/napcat') as List;
      if (!mounted) return;
      setState(() => targets = ['astrbot', ...rows.map((e) => e['container'].toString()), 'agent']);
    } catch (_) {}
  }

  void _open() {
    sub?.cancel();
    lines.clear();
    buffered.clear();
    error = null;
    sub = conn!.api!
        .logStream(target, tail: 400)
        .listen(
          (m) {
            if (m['type'] == 'error') {
              setState(() => error = m['message']?.toString());
              return;
            }
            if (paused) {
              buffered.add(m);
              return;
            }
            _append([m]);
          },
          onError: (e) => mounted ? setState(() => error = e.toString()) : null,
          onDone: () {
            sub = null;
            if (mounted && widget.active) {
              Future.delayed(const Duration(seconds: 2), () {
                if (mounted) _sync();
              });
            }
          },
        );
    setState(() {});
  }

  void _append(List<Map<String, dynamic>> items) {
    if (!mounted) return;
    setState(() {
      lines.addAll(items);
      if (lines.length > 5000) lines.removeRange(0, lines.length - 5000);
    });
    if (follow) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
      });
    }
  }

  void _switch(String t) {
    setState(() => target = t);
    if (conn?.api != null && widget.active) _open();
  }

  @override
  void dispose() {
    widget.target.removeListener(_onTarget);
    conn?.removeListener(_onConn);
    sub?.cancel();
    scroll.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get visible => lines.where((l) {
    if (level != 'ALL' && l['level'] != level) return false;
    if (query.isNotEmpty && !l['text'].toString().toLowerCase().contains(query.toLowerCase())) return false;
    return true;
  }).toList();

  String _export() => visible.map((l) => '${l['time']} [${l['level']}] ${l['text']}').join('\n');

  Future<void> _save() async {
    final name = 'nailong-$target-${DateTime.now().toIso8601String().substring(0, 19).replaceAll(':', '')}.log';
    try {
      await FilePicker.saveFile(
        fileName: name,
        bytes: Uint8List.fromList(utf8.encode(_export())),
        mimeType: 'text/plain',
      );
    } catch (e) {
      if (mounted) toast(context, '导出失败：$e');
    }
  }

  String _label(String t) => switch (t) {
    'astrbot' => 'AstrBot',
    'agent' => '奶龙 Agent',
    _ => t,
  };

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final rows = visible;
    return Scaffold(
      appBar: AppBar(
        title: const Text('实时日志'),
        actions: [
          IconButton(
            tooltip: raw ? '简洁模式' : '原始日志',
            icon: Icon(raw ? Icons.notes : Icons.data_object),
            onPressed: () => setState(() => raw = !raw),
          ),
          IconButton(
            tooltip: paused ? '继续' : '暂停',
            icon: Icon(paused ? Icons.play_arrow : Icons.pause),
            onPressed: () {
              setState(() => paused = !paused);
              if (!paused && buffered.isNotEmpty) {
                _append([...buffered]);
                buffered.clear();
              }
            },
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              if (v == 'copy') copyText(context, _export(), label: '日志');
              if (v == 'export') _save();
              if (v == 'clear') setState(lines.clear);
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'copy',
                child: ListTile(leading: Icon(Icons.copy_all), title: Text('复制')),
              ),
              PopupMenuItem(
                value: 'export',
                child: ListTile(leading: Icon(Icons.download), title: Text('导出到手机')),
              ),
              PopupMenuItem(
                value: 'clear',
                child: ListTile(leading: Icon(Icons.clear_all), title: Text('清屏')),
              ),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final t in targets)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(_label(t)),
                      selected: t == target,
                      showCheckmark: false,
                      onSelected: (_) => _switch(t),
                    ),
                  ),
              ],
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final l in _levels)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilterChip(
                      label: Text(l == 'ALL' ? '全部' : l),
                      selected: level == l,
                      showCheckmark: false,
                      onSelected: (_) => setState(() => level = l),
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TextField(
              onChanged: (v) => setState(() => query = v),
              decoration: const InputDecoration(isDense: true, hintText: '搜索日志', prefixIcon: Icon(Icons.search)),
            ),
          ),
          if (paused && buffered.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text('已暂停 · ${buffered.length} 条新日志待显示', style: TextStyle(color: cs.accentText, fontSize: 12)),
            ),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              decoration: BoxDecoration(color: cs.surfaceContainer, borderRadius: BorderRadius.circular(16)),
              clipBehavior: Clip.antiAlias,
              child: conn?.api == null
                  ? const LoadingView()
                  : error != null && lines.isEmpty
                  ? MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: _open)
                  : rows.isEmpty
                  ? const MessageView(icon: Icons.receipt_long_outlined, text: '暂无日志')
                  : NotificationListener<UserScrollNotification>(
                      onNotification: (n) {
                        final atEnd = scroll.position.pixels >= scroll.position.maxScrollExtent - 40;
                        if (atEnd != follow) setState(() => follow = atEnd);
                        return false;
                      },
                      child: ListView.builder(
                        controller: scroll,
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        itemCount: rows.length,
                        itemBuilder: (_, i) => _LogLine(line: rows[i], raw: raw),
                      ),
                    ),
            ),
          ),
        ],
      ),
      floatingActionButton: follow
          ? null
          : FloatingActionButton.small(
              onPressed: () {
                setState(() => follow = true);
                scroll.jumpTo(scroll.position.maxScrollExtent);
              },
              child: const Icon(Icons.vertical_align_bottom),
            ),
    );
  }
}

class _LogLine extends StatelessWidget {
  final Map<String, dynamic> line;
  final bool raw;

  const _LogLine({required this.line, required this.raw});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final lv = line['level']?.toString() ?? 'INFO';
    final color = switch (lv) {
      'ERROR' => cs.error,
      'WARNING' => cs.warning,
      'DEBUG' => cs.outline,
      _ => cs.onSurface,
    };
    final hint = line['hint']?.toString() ?? '';
    if (raw) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 1),
        child: SelectableText(
          '${line['time']} ${line['text']}',
          style: TextStyle(fontFamily: 'monospace', fontSize: 11, height: 1.4, color: color),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 46,
            alignment: Alignment.center,
            margin: const EdgeInsets.only(top: 2),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(6)),
            child: Text(
              lv.substring(0, lv.length.clamp(0, 4)),
              style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (hint.isNotEmpty)
                  Text(
                    hint,
                    style: TextStyle(fontWeight: FontWeight.w700, color: cs.accentText, fontSize: 12.5),
                  ),
                SelectableText(
                  line['text'].toString(),
                  style: TextStyle(fontSize: 12, height: 1.4, color: lv == 'INFO' ? null : color),
                ),
                Text(line['time']?.toString() ?? '', style: TextStyle(fontSize: 10.5, color: cs.outline)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
