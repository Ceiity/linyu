import 'dart:async';
import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

import '../core/agent_api.dart';
import 'theme.dart';

// ---------- 卡片 ----------

/// FlClash 风格信息卡：顶部图标 + 标题，下方内容。
class InfoCard extends StatelessWidget {
  final IconData? icon;
  final String? title;
  final List<Widget> actions;
  final Widget child;
  final VoidCallback? onTap;
  final bool selected;
  final EdgeInsetsGeometry padding;

  const InfoCard({
    super.key,
    this.icon,
    this.title,
    this.actions = const [],
    required this.child,
    this.onTap,
    this.selected = false,
    this.padding = const EdgeInsets.fromLTRB(16, 14, 16, 16),
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: selected ? cs.secondaryContainer : cs.surfaceContainer,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: padding,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (title != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: SizedBox(
                    height: 28,
                    child: Row(
                      children: [
                        if (icon != null) ...[
                          Icon(icon, size: 20, color: cs.onSurfaceVariant),
                          const SizedBox(width: 10),
                        ],
                        Expanded(
                          child: Text(
                            title!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(fontWeight: FontWeight.w600, color: cs.onSurfaceVariant),
                          ),
                        ),
                        ...actions,
                      ],
                    ),
                  ),
                ),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  final String text;
  final Widget? trailing;

  const SectionTitle(this.text, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 20, 16, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(color: cs.accentText, fontWeight: FontWeight.w700),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// 分组列表容器（工具页、设置页）。
class GroupCard extends StatelessWidget {
  final List<Widget> children;

  const GroupCard({super.key, required this.children});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final items = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      items.add(children[i]);
      if (i != children.length - 1) {
        items.add(Divider(height: 1, indent: 56, color: cs.outlineVariant.withValues(alpha: 0.4)));
      }
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Material(
        color: cs.surfaceContainer,
        borderRadius: BorderRadius.circular(16),
        clipBehavior: Clip.antiAlias,
        child: Column(children: items),
      ),
    );
  }
}

// ---------- 状态标签 ----------

enum Tone { ok, warn, bad, info, idle }

Color toneColor(ColorScheme cs, Tone t) => switch (t) {
  Tone.ok => cs.success,
  Tone.warn => cs.warning,
  Tone.bad => cs.error,
  Tone.info => cs.accentText,
  Tone.idle => cs.outline,
};

class StatusChip extends StatelessWidget {
  final String text;
  final Tone tone;
  final bool dot;

  const StatusChip(this.text, this.tone, {super.key, this.dot = true});

  @override
  Widget build(BuildContext context) {
    final c = toneColor(Theme.of(context).colorScheme, tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(99)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (dot) ...[
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: c, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
          ],
          Text(
            text,
            style: TextStyle(color: c, fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

String containerStatusText(String? s) => switch (s) {
  'running' => '运行中',
  'exited' => '已停止',
  'created' => '已创建',
  'restarting' => '重启中',
  'paused' => '已暂停',
  'dead' => '异常',
  'missing' => '不存在',
  _ => s == null || s.isEmpty ? '未知' : s,
};

Tone containerTone(String? s) => switch (s) {
  'running' => Tone.ok,
  'exited' => Tone.idle,
  'restarting' || 'created' || 'paused' => Tone.warn,
  _ => Tone.bad,
};

String botName(String? n) {
  final m = RegExp(r'^napcat0*(\d+)$').firstMatch(n ?? '');
  return m != null ? '机器人${int.parse(m.group(1)!)}' : (n == null || n.isEmpty ? '机器人' : n);
}

String fmtBytes(num? b) {
  var v = (b ?? 0).toDouble();
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return '${v.toStringAsFixed(i == 0 ? 0 : 1)} ${units[i]}';
}

// ---------- 图表 ----------

class RingGauge extends StatelessWidget {
  final double percent;
  final String label;
  final Color? color;
  final double size;

  const RingGauge({super.key, required this.percent, required this.label, this.color, this.size = 76});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final c =
        color ??
        (percent >= 90
            ? cs.error
            : percent >= 75
            ? cs.warning
            : cs.primary);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: size,
          height: size,
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: percent.clamp(0, 100) / 100),
            duration: const Duration(milliseconds: 600),
            curve: Curves.easeOutCubic,
            builder: (_, v, _) => CustomPaint(
              painter: _RingPainter(v, c, cs.surfaceContainerHighest),
              child: Center(
                child: Text(
                  '${percent.round()}%',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(label, style: Theme.of(context).textTheme.labelMedium?.copyWith(color: cs.onSurfaceVariant)),
      ],
    );
  }
}

class _RingPainter extends CustomPainter {
  final double v;
  final Color color;
  final Color track;

  _RingPainter(this.v, this.color, this.track);

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 8.0;
    final rect = Offset.zero & size;
    final r = rect.deflate(stroke / 2);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(r, 0, math.pi * 2, false, p..color = track);
    if (v > 0) canvas.drawArc(r, -math.pi / 2, math.pi * 2 * v, false, p..color = color);
  }

  @override
  bool shouldRepaint(_RingPainter o) => o.v != v || o.color != color || o.track != track;
}

/// 平滑折线 + 渐变填充（仿 FlClash 流量图）。
class SparkLine extends StatelessWidget {
  final List<double> values;
  final List<double>? values2;
  final double maxValue;
  final double height;

  const SparkLine({super.key, required this.values, this.values2, this.maxValue = 100, this.height = 110});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: CustomPaint(painter: _SparkPainter(values, values2, maxValue, cs.primary, cs.tertiary, cs.outlineVariant)),
    );
  }
}

class _SparkPainter extends CustomPainter {
  final List<double> a;
  final List<double>? b;
  final double maxV;
  final Color ca, cb, grid;

  _SparkPainter(this.a, this.b, this.maxV, this.ca, this.cb, this.grid);

  static const samples = 30;

  Path _path(List<double> vs, Size s) {
    final path = Path();
    final pts = <Offset>[];
    final start = samples - vs.length;
    for (var i = 0; i < vs.length; i++) {
      final x = s.width * (start + i) / (samples - 1);
      final y = s.height - (vs[i].clamp(0, maxV) / maxV) * (s.height - 6) - 3;
      pts.add(Offset(x, y));
    }
    if (pts.isEmpty) return path;
    path.moveTo(pts.first.dx, pts.first.dy);
    for (var i = 1; i < pts.length; i++) {
      final p0 = pts[i - 1], p1 = pts[i];
      final mx = (p0.dx + p1.dx) / 2;
      path.cubicTo(mx, p0.dy, mx, p1.dy, p1.dx, p1.dy);
    }
    return path;
  }

  void _draw(Canvas canvas, Size s, List<double> vs, Color c) {
    if (vs.length < 2) return;
    final line = _path(vs, s);
    final startX = s.width * (samples - vs.length) / (samples - 1);
    final fill = Path.from(line)
      ..lineTo(s.width, s.height)
      ..lineTo(startX, s.height)
      ..close();
    canvas.drawPath(
      fill,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [c.withValues(alpha: 0.28), c.withValues(alpha: 0.0)],
        ).createShader(Offset.zero & s),
    );
    canvas.drawPath(
      line,
      Paint()
        ..color = c
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.2
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  void paint(Canvas canvas, Size s) {
    final gp = Paint()
      ..color = grid.withValues(alpha: 0.35)
      ..strokeWidth = 1;
    for (var i = 1; i < 4; i++) {
      final y = s.height * i / 4;
      canvas.drawLine(Offset(0, y), Offset(s.width, y), gp);
    }
    if (b != null) _draw(canvas, s, b!, cb);
    _draw(canvas, s, a, ca);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter o) => true;
}

// ---------- 状态视图 ----------

class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) => const Center(child: CircularProgressIndicator());
}

class MessageView extends StatelessWidget {
  final IconData icon;
  final String text;
  final String? actionText;
  final VoidCallback? onAction;

  const MessageView({super.key, required this.icon, required this.text, this.actionText, this.onAction});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: cs.outline),
            const SizedBox(height: 12),
            Text(
              text,
              textAlign: TextAlign.center,
              style: TextStyle(color: cs.onSurfaceVariant),
            ),
            if (actionText != null) ...[
              const SizedBox(height: 16),
              FilledButton.tonal(onPressed: onAction, child: Text(actionText!)),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------- 提示与对话框 ----------

void toast(BuildContext context, String msg) {
  final m = ScaffoldMessenger.maybeOf(context);
  m?.hideCurrentSnackBar();
  m?.showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));
}

void copyText(BuildContext context, String text, {String? label}) {
  if (text.isEmpty) return;
  Clipboard.setData(ClipboardData(text: text));
  toast(context, '${label ?? '内容'}已复制');
}

Future<bool> confirmDialog(
  BuildContext context, {
  required String title,
  String? message,
  String confirmText = '确认',
  bool destructive = false,
}) async {
  final cs = Theme.of(context).colorScheme;
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: message == null ? null : Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')),
        FilledButton(
          style: destructive ? FilledButton.styleFrom(backgroundColor: cs.error, foregroundColor: cs.onError) : null,
          onPressed: () => Navigator.pop(c, true),
          child: Text(confirmText),
        ),
      ],
    ),
  );
  return r == true;
}

/// 需要手动输入确认词的危险操作。
Future<bool> typeConfirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  required String word,
}) async {
  final ctrl = TextEditingController();
  final cs = Theme.of(context).colorScheme;
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => StatefulBuilder(
      builder: (c, set) => AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(message),
            const SizedBox(height: 12),
            Text('请输入 “$word” 确认', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
            const SizedBox(height: 8),
            TextField(controller: ctrl, autofocus: true, onChanged: (_) => set(() {})),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('取消')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: cs.error, foregroundColor: cs.onError),
            onPressed: ctrl.text.trim() == word ? () => Navigator.pop(c, true) : null,
            child: const Text('确认'),
          ),
        ],
      ),
    ),
  );
  return r == true;
}

/// 执行请求并统一提示错误。
Future<T?> runAction<T>(BuildContext context, Future<T> Function() fn, {String? success}) async {
  try {
    final r = await fn();
    if (success != null && context.mounted) toast(context, success);
    return r;
  } catch (e) {
    if (context.mounted) toast(context, e.toString());
    return null;
  }
}

// ---------- 任务进度（Agent 后台任务） ----------

String taskStatusText(String? s) => switch (s) {
  'running' => '执行中',
  'success' => '成功',
  'failed' => '失败',
  _ => s ?? '未知',
};

Tone taskTone(String? s) => switch (s) {
  'success' => Tone.ok,
  'failed' => Tone.bad,
  'running' => Tone.info,
  _ => Tone.idle,
};

/// 提交返回任务的请求后，弹出进度直至完成。返回任务最终结果。
Future<Map<String, dynamic>?> runTask(BuildContext context, AgentApi api, Future<dynamic> Function() submit) async {
  final t = await runAction(context, submit);
  if (t is! Map || t['id'] == null || !context.mounted) return null;
  return showModalBottomSheet<Map<String, dynamic>>(
    context: context,
    isDismissible: false,
    useSafeArea: true,
    builder: (_) => _TaskSheet(api: api, id: t['id'].toString(), title: t['title']?.toString() ?? '任务'),
  );
}

class _TaskSheet extends StatefulWidget {
  final AgentApi api;
  final String id;
  final String title;

  const _TaskSheet({required this.api, required this.id, required this.title});

  @override
  State<_TaskSheet> createState() => _TaskSheetState();
}

class _TaskSheetState extends State<_TaskSheet> {
  Map<String, dynamic>? task;
  StreamSubscription? sub;
  String? error;

  @override
  void initState() {
    super.initState();
    sub = widget.api
        .watchTask(widget.id)
        .listen((t) => setState(() => task = t), onError: (e) => setState(() => error = e.toString()));
  }

  @override
  void dispose() {
    sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final st = task?['status']?.toString() ?? 'running';
    final done = st != 'running';
    final p = (task?['progress'] as num?)?.toDouble();
    final result = task?['result'];
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  widget.title,
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              StatusChip(taskStatusText(st), taskTone(st)),
            ],
          ),
          const SizedBox(height: 18),
          ClipRRect(
            borderRadius: BorderRadius.circular(99),
            child: LinearProgressIndicator(
              value: done ? 1 : (p == null ? null : p / 100),
              minHeight: 8,
              color: st == 'failed' ? cs.error : null,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            error ??
                (st == 'failed'
                    ? (task?['message']?.toString() ?? '失败')
                    : st == 'success'
                    ? ((result is Map ? result['message'] : null)?.toString() ?? '完成')
                    : (task?['message']?.toString().isNotEmpty == true ? task!['message'].toString() : '请稍候…')),
            style: TextStyle(color: st == 'failed' || error != null ? cs.error : cs.onSurfaceVariant),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: () => Navigator.pop(context, task),
              child: Text(done || error != null ? '完成' : '后台运行'),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------- 轮询 ----------

/// 页面可见且应用在前台时定时刷新。
mixin PollingMixin<T extends StatefulWidget> on State<T>, WidgetsBindingObserver {
  Timer? _pollTimer;
  bool _polling = false;

  Duration get pollInterval;

  bool get pollActive;

  Future<void> poll();

  void initPolling() {
    WidgetsBinding.instance.addObserver(this);
    syncPolling();
  }

  void disposePolling() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
  }

  void syncPolling() {
    final resumed =
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.paused &&
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.hidden;
    if (pollActive && resumed) {
      if (_pollTimer == null) {
        _tick();
        _pollTimer = Timer.periodic(pollInterval, (_) => _tick());
      }
    } else {
      _pollTimer?.cancel();
      _pollTimer = null;
    }
  }

  Future<void> _tick() async {
    if (_polling || !mounted) return;
    _polling = true;
    try {
      await poll();
    } finally {
      _polling = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) => syncPolling();
}

// ---------- 品牌与格式 ----------

class AppLogo extends StatelessWidget {
  final double size;

  const AppLogo({super.key, this.size = 64});

  @override
  Widget build(BuildContext context) =>
      Image.asset('assets/brand/logo.png', width: size, height: size, filterQuality: FilterQuality.medium);
}

String fmtSpeed(num? bps) => '${fmtBytes(bps ?? 0)}/s';

String fmtDuration(int seconds) {
  if (seconds < 60) return '$seconds 秒';
  if (seconds < 3600) return '${seconds ~/ 60} 分钟';
  if (seconds < 86400) return '${seconds ~/ 3600} 小时 ${(seconds % 3600) ~/ 60} 分';
  return '${seconds ~/ 86400} 天 ${(seconds % 86400) ~/ 3600} 小时';
}
