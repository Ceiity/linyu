import 'dart:async';

import 'package:material_ui/material_ui.dart';

import 'agent_api.dart';
import 'errors.dart';
import 'installer.dart';
import 'keys.dart';
import 'ssh.dart';
import 'store.dart';

enum StepStatus { pending, running, done, skipped, kept, warning, failed }

class DeployStep {
  final String id;
  String title;
  StepStatus status = StepStatus.pending;
  String message = '';
  double? percent;
  int? speed;

  DeployStep(this.id, this.title);
}

enum FlowPhase { idle, connecting, detecting, report, deploying, pairing, success, failed, cancelled }

/// 一键部署流程（也用于已有服务器的重新配对）。
class DeployFlow extends ChangeNotifier {
  final AppStore store;

  DeployFlow(this.store);

  FlowPhase phase = FlowPhase.idle;
  String status = '';
  NailongError? error;
  SshTarget? target;
  SshSession? ssh;
  ServerInstaller? installer;
  Preflight? preflight;
  Map<String, dynamic>? report;
  ServerProfile? result;
  bool savePassword = false;
  bool installFail2ban = true;
  bool cancelRequested = false;
  final logs = <String>[];

  final steps = <DeployStep>[
    DeployStep('connect', '连接服务器'),
    DeployStep('detect', '环境检测'),
    DeployStep('deps', '安装基础依赖'),
    DeployStep('fail2ban', '配置 Fail2Ban 防暴力破解'),
    DeployStep('docker', '安装 Docker'),
    DeployStep('images', '下载 AstrBot / NapCat 镜像'),
    DeployStep('astrbot', '部署 AstrBot'),
    DeployStep('napcat', '部署 NapCat'),
    DeployStep('onebot', '配置 OneBot v11'),
    DeployStep('agent', '安装奶龙 Agent'),
    DeployStep('verify', '服务启动验证'),
    DeployStep('pair', '安全配对'),
    DeployStep('tunnel', '连接验证'),
  ];

  DeployStep step(String id) => steps.firstWhere((s) => s.id == id, orElse: () => steps.first);

  void _log(String line) {
    logs.add(line);
    if (logs.length > 3000) logs.removeRange(0, 500);
  }

  bool _disposed = false;
  bool reconnecting = false;

  void _update() {
    if (!_disposed) notifyListeners();
  }

  /// 部署在服务器上独立运行；手机切后台/断网后 SSH 会断，这里用已核对过的指纹静默重连。
  Future<SshSession> _reconnectSsh() async {
    final t = target!;
    final s = await SshSession.connect(
      t,
      knownFingerprint: ssh?.hostKeyFingerprint ?? store.knownHost(t.hostKeyId),
      decide: (a, b, c) => false,
      retries: 0,
    );
    ssh = s;
    return s;
  }

  void _fail(Object e, [String? stepId]) {
    error = e is NailongError ? e : NailongError('ERROR', e.toString());
    if (stepId != null) {
      step(stepId)
        ..status = StepStatus.failed
        ..message = error!.message;
    }
    phase = error!.code == 'CANCELLED' ? FlowPhase.cancelled : FlowPhase.failed;
    _update();
  }

  /// 第 1 步：连接（首次需用户核对主机指纹）+ 预检 + 上传组件 + 环境检测。
  Future<void> connectAndDetect(SshTarget t, HostKeyDecider decide) async {
    target = t;
    error = null;
    report = null;
    phase = FlowPhase.connecting;
    for (final s in steps) {
      s
        ..status = StepStatus.pending
        ..message = ''
        ..percent = null;
    }
    step('connect').status = StepStatus.running;
    status = '正在连接 ${t.host}:${t.port}';
    _update();
    try {
      ssh?.close();
      ssh = await SshSession.connect(
        t,
        knownFingerprint: store.knownHost(t.hostKeyId),
        decide: (type, fp, known) async {
          final ok = await decide(type, fp, known);
          if (ok) await store.trustHost(t.hostKeyId, fp);
          return ok;
        },
      );
      if (!ssh!.canElevate) {
        throw NailongError('NO_ROOT', '需要 root 权限：请使用 root 登录，或使用有 sudo 权限的用户并填写密码');
      }
      step('connect')
        ..status = StepStatus.done
        ..message = '已连接（${ssh!.hostKeyFingerprint.substring(0, 20)}…）';
      phase = FlowPhase.detecting;
      step('detect').status = StepStatus.running;
      status = '正在检测服务器环境';
      _update();
      installer = ServerInstaller(ssh!, reconnect: _reconnectSsh);
      preflight = await installer!.preflight();
      if (!preflight!.hasPython) {
        if (!preflight!.hasApt) {
          throw NailongError('UNSUPPORTED_OS', '暂不支持该系统（${preflight!.osPretty}），请使用 Ubuntu 或 Debian');
        }
        status = '安装 Python 3 运行环境';
        _update();
        await installer!.installPython(_log);
      }
      await installer!.ensureBundle(
        onStatus: (s) {
          status = s;
          _update();
        },
      );
      status = '正在检测服务器环境';
      _update();
      report = await installer!.detect();
      step('detect')
        ..status = StepStatus.done
        ..message = '${report!['os']?['pretty'] ?? ''} · ${report!['os']?['arch'] ?? ''}';
      _applyPlan(Map<String, dynamic>.from(report!['plan'] as Map));
      phase = FlowPhase.report;
      _update();
      if (report!['deploy']?['running'] == true) {
        // 上次的部署还在服务器上运行（比如 App 被切走/回收了）：直接接上进度，不重新开始
        status = '服务器上有一个正在进行的部署，正在接上进度…';
        await deploy(attach: true);
      }
    } catch (e) {
      _fail(e, step('connect').status == StepStatus.done ? 'detect' : 'connect');
    }
  }

  void _applyPlan(Map<String, dynamic> plan) {
    for (final s in (plan['steps'] as List)) {
      final m = Map<String, dynamic>.from(s as Map);
      final st = step(m['id'] as String);
      if (st.id != m['id']) continue;
      st.message = m['detail']?.toString() ?? '';
      if (m['action'] == 'skip') st.status = StepStatus.skipped;
      if (m['action'] == 'keep') st.status = StepStatus.kept;
    }
  }

  Map<String, dynamic> get plan => Map<String, dynamic>.from((report?['plan'] ?? {}) as Map);

  List<String> get blockers => ((plan['blockers'] ?? []) as List).map((e) => e.toString()).toList();

  /// 第 2 步：用户确认后执行部署（也用于“继续部署”）。
  Future<void> deploy({bool attach = false}) async {
    if (installer == null || target == null) return;
    error = null;
    cancelRequested = false;
    phase = FlowPhase.deploying;
    for (final s in steps.where((s) => s.status == StepStatus.failed)) {
      s.status = StepStatus.pending;
    }
    status = '正在部署';
    _update();
    Map<String, dynamic>? res;
    try {
      await for (final ev in installer!.deploy(attach: attach, {
        'ssh_user': target!.user,
        'sources': store.sources.forInstaller(),
        'timezone': 'Asia/Shanghai',
        'fail2ban': installFail2ban,
      })) {
        if (ev.type != 'reconnecting') reconnecting = false;
        switch (ev.type) {
          case 'reconnecting':
            reconnecting = true;
            status = ev.data['message']?.toString() ?? '正在重连…';
          case 'step_start':
            step(ev.id)
              ..status = StepStatus.running
              ..message = ''
              ..percent = null;
            status = ev.data['title']?.toString() ?? status;
          case 'step_progress':
            final s = step(ev.id);
            s.percent = (ev.data['percent'] as num?)?.toDouble();
            s.message = ev.data['message']?.toString() ?? s.message;
            s.speed = (ev.data['speed'] as num?)?.toInt();
            status = s.message;
          case 'step_done':
            final s = step(ev.id);
            s.status = switch (ev.data['status']) {
              'skipped' => StepStatus.skipped,
              'kept' => StepStatus.kept,
              'warning' => StepStatus.warning,
              _ => StepStatus.done,
            };
            s.message = ev.data['message']?.toString() ?? '';
            s.percent = null;
            s.speed = null;
          case 'log':
            _log(ev.data['line']?.toString() ?? '');
          case 'error':
            _log('错误：${ev.data['message']} ${ev.data['detail'] ?? ''}');
          case 'result':
            res = ev.data;
        }
        _update();
      }
      if (res == null) throw NailongError('DISCONNECTED', '与服务器的连接中断，可稍后继续部署');
      if (res['ok'] != true) {
        final code = res['code']?.toString() ?? 'ERROR';
        throw NailongError(
          code,
          res['message']?.toString() ?? installerHints[code] ?? '部署失败',
          res['detail']?.toString() ?? '',
        );
      }
      await pairAndSave(agentPort: (res['agent_port'] as num).toInt());
    } catch (e) {
      final running = steps.where((s) => s.status == StepStatus.running).firstOrNull;
      _fail(e, running?.id);
    }
  }

  Future<void> cancel() async {
    if (phase != FlowPhase.deploying || installer == null) return;
    cancelRequested = true;
    status = '正在安全停止…';
    _update();
    try {
      await installer!.cancel();
    } catch (_) {}
  }

  /// 配对：生成本机密钥 → 写入受限公钥 → 获取一次性配对码 → 隧道内配对 → 用新密钥验证。
  Future<void> pairAndSave({required int agentPort, ServerProfile? existing}) async {
    phase = FlowPhase.pairing;
    final pairStep = step('pair')
      ..status = StepStatus.running
      ..message = '生成设备密钥';
    status = '安全配对中';
    _update();
    final profileId = existing?.id ?? newId();
    final deviceId = existing?.deviceId.isNotEmpty == true ? existing!.deviceId : 'nl-${newId(12)}';
    final key = DeviceKey.generate('nailong:$deviceId');
    await installer!.authorizeKey(user: target!.user, publicLine: key.publicLine, deviceId: deviceId, port: agentPort);
    pairStep.message = '获取一次性配对码';
    _update();
    final code = await installer!.pairCode();
    final tunnel = LocalTunnel(ssh!, agentPort);
    await tunnel.open();
    Map<String, dynamic> pair;
    try {
      final api = AgentApi(tunnel.localPort);
      pair = Map<String, dynamic>.from(
        await api.post('/api/pair', {'code': code, 'device_name': 'Android · 奶龙', 'device_id': deviceId}) as Map,
      );
      api.close();
    } finally {
      await tunnel.close();
    }
    pairStep
      ..status = StepStatus.done
      ..message = '设备已授权';
    final verify = step('tunnel')
      ..status = StepStatus.running
      ..message = '使用设备密钥建立 SSH 隧道';
    _update();
    // 用新密钥（仅能转发到 Agent 端口）验证真实连接
    final keySession = await SshSession.connect(
      SshTarget(host: target!.host, port: target!.port, user: target!.user, privateKeyPem: key.privatePem),
      knownFingerprint: ssh!.hostKeyFingerprint,
      decide: (a, b, c) => false,
      probePrivileges: false,
    );
    final t2 = LocalTunnel(keySession, agentPort);
    await t2.open();
    try {
      final api = AgentApi(t2.localPort, token: pair['token'] as String);
      await api.get('/api/me');
      api.close();
    } finally {
      await t2.close();
      keySession.close();
    }
    verify
      ..status = StepStatus.done
      ..message = '安全通道正常';
    final profile = ServerProfile(
      id: profileId,
      name: existing?.name ?? (report?['hostname']?.toString() ?? target!.host),
      host: target!.host,
      port: target!.port,
      user: target!.user,
      hostKey: ssh!.hostKeyFingerprint,
      agentPort: agentPort,
      deviceId: deviceId,
      lastOnline: DateTime.now().millisecondsSinceEpoch,
    );
    await store.setSecret('key', profileId, key.privatePem);
    await store.setSecret('token', profileId, pair['token'] as String);
    await store.setSecret('tokexp', profileId, '${pair['expires_at']}');
    await store.setSecret('pw', profileId, savePassword ? target!.password : null);
    await store.upsertServer(profile);
    result = profile;
    phase = FlowPhase.success;
    status = '部署成功';
    _update();
    ssh?.close();
  }

  /// 已部署服务器：只做重新配对（需要 SSH 密码/私钥）。
  Future<void> repair(SshTarget t, ServerProfile existing, HostKeyDecider decide) async {
    await connectAndDetect(t, decide);
    if (phase != FlowPhase.report) return;
    final agent = report?['state']?['agent'];
    if (agent == null || agent['port'] == null) {
      _fail(NailongError('NO_AGENT', '该服务器还没有部署奶龙 Agent，请执行部署'));
      return;
    }
    try {
      await pairAndSave(agentPort: (agent['port'] as num).toInt(), existing: existing);
    } catch (e) {
      _fail(e, 'pair');
    }
  }

  @override
  void dispose() {
    _disposed = true;
    installer?.stopWatching();
    ssh?.close();
    super.dispose();
  }
}
