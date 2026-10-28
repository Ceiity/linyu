import 'package:material_ui/material_ui.dart';

import '../core/app_state.dart';
import '../ui/theme.dart';
import '../ui/widgets.dart';

class LogsPage extends StatefulWidget {
  final bool active;
  final ValueNotifier<String?> target;

  const LogsPage({super.key, required this.active, required this.target});

  @override
  State<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends State<LogsPage> with WidgetsBindingObserver, PollingMixin {
  String target = 'astrbot';
  List<String> robots = [];
  List<String> lines = [];
  String? error;
  bool live = true;
  bool follow = true;
  bool loaded = false;
  final keyword = TextEditingController();
  final scroll = ScrollController();

  @override
  Duration get pollInterval => const Duration(milliseconds: 2500);

  @override
  bool get pollActive => widget.active && live;

  @override
  void initState() {
    super.initState();
    widget.target.addListener(_onTarget);
    _loadRobots();
    initPolling();
  }

  @override
  void didUpdateWidget(LogsPage old) {
    super.didUpdateWidget(old);
    syncPolling();
  }

  @override
  void dispose() {
    widget.target.removeListener(_onTarget);
    disposePolling();
    keyword.dispose();
    scroll.dispose();
    super.dispose();
  }

  void _onTarget() {
    final t = widget.target.value;
    if (t == null) return;
    widget.target.value = null;
    if (!robots.contains(t) && !['astrbot', 'deploy', 'panel'].contains(t)) robots = [...robots, t];
    _switch(t);
  }

  void _switch(String t) {
    setState(() {
      target = t;
      lines = [];
      loaded = false;
      follow = true;
    });
    poll();
  }

  Future<void> _loadRobots() async {
    try {
      final d = await AppScope.read(context).api!.get('/api/napcat');
      if (!mounted) return;
      setState(() => robots = (d as List).map((e) => e['name'].toString()).toList());
    } catch (_) {}
  }

  @override
  Future<void> poll() async {
    final api = AppScope.read(context).api;
    if (api == null) return;
    try {
      final d = await api.get('/api/logs', query: {'target': target, 'keyword': keyword.text.trim(), 'lines': '500'});
      if (!mounted) return;
      final content = (d['content'] ?? '').toString();
      setState(() {
        lines = content.isEmpty ? [] : content.split('\n');
        error = null;
        loaded = true;
      });
      if (follow) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Color? _lineColor(ColorScheme cs, String l) {
    final s = l.toLowerCase();
    if (s.contains('error') ||
        s.contains('exception') ||
        s.contains('traceback') ||
        l.contains('错误') ||
        l.contains('失败')) {
      return cs.error;
    }
    if (s.contains('warn') || l.contains('警告')) return cs.warning;
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final targets = [
      ('astrbot', 'AstrBot'),
      ('deploy', '部署脚本'),
      ('panel', '面板审计'),
      for (final r in robots) (r, botName(r)),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('日志'),
        actions: [
          IconButton(
            tooltip: live ? '暂停实时' : '开启实时',
            icon: Icon(live ? Icons.pause_circle_outline : Icons.play_circle_outline),
            onPressed: () {
              setState(() => live = !live);
              syncPolling();
            },
          ),
          IconButton(
            tooltip: '复制',
            icon: const Icon(Icons.copy_all_outlined),
            onPressed: () => copyText(context, lines.join('\n'), label: '日志'),
          ),
          IconButton(tooltip: '刷新', icon: const Icon(Icons.refresh), onPressed: poll),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final t in targets)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(t.$2),
                      selected: target == t.$1,
                      showCheckmark: false,
                      onSelected: (_) => _switch(t.$1),
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TextField(
              controller: keyword,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => poll(),
              decoration: InputDecoration(
                isDense: true,
                hintText: '关键词过滤，例如 error',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: keyword.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () {
                          keyword.clear();
                          poll();
                        },
                      ),
              ),
              onChanged: (_) => setState(() {}),
            ),
          ),
          Expanded(
            child: Container(
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              decoration: BoxDecoration(color: cs.surfaceContainer, borderRadius: BorderRadius.circular(16)),
              clipBehavior: Clip.antiAlias,
              child: !loaded
                  ? (error == null
                        ? const LoadingView()
                        : MessageView(icon: Icons.cloud_off, text: error!, actionText: '重试', onAction: poll))
                  : lines.isEmpty
                  ? const MessageView(icon: Icons.receipt_long_outlined, text: '暂无日志')
                  : NotificationListener<ScrollNotification>(
                      onNotification: (n) {
                        if (n is UserScrollNotification) {
                          final atEnd = scroll.position.pixels >= scroll.position.maxScrollExtent - 40;
                          if (follow != atEnd) setState(() => follow = atEnd);
                        }
                        return false;
                      },
                      child: Scrollbar(
                        controller: scroll,
                        child: ListView.builder(
                          controller: scroll,
                          padding: const EdgeInsets.all(12),
                          itemCount: lines.length,
                          itemBuilder: (_, i) => SelectableText(
                            lines[i],
                            style: TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 11.5,
                              height: 1.45,
                              color: _lineColor(cs, lines[i]),
                            ),
                          ),
                        ),
                      ),
                    ),
            ),
          ),
        ],
      ),
      floatingActionButton: follow || lines.isEmpty
          ? null
          : FloatingActionButton.small(
              onPressed: () {
                setState(() => follow = true);
                scroll.animateTo(
                  scroll.position.maxScrollExtent,
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeOut,
                );
              },
              child: const Icon(Icons.vertical_align_bottom),
            ),
    );
  }
}
