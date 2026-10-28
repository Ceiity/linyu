import 'dart:async';
import 'dart:io';

import 'package:dartssh2/dartssh2.dart';

/// 普通用户看得懂的错误。
class NailongError implements Exception {
  final String code;
  final String message;
  final String detail;

  NailongError(this.code, this.message, [this.detail = '']);

  @override
  String toString() => message;

  factory NailongError.fromSsh(Object e) {
    final s = e.toString();
    if (e is SSHAuthFailError || e is SSHAuthAbortError || s.contains('SSHAuthFailError')) {
      return NailongError('AUTH_FAILED', '用户名或密码错误（或私钥未被服务器接受）', s);
    }
    if (e is TimeoutException || s.contains('TimeoutException') || s.contains('timed out')) {
      return NailongError('TIMEOUT', '服务器连接超时，请检查 IP 地址、SSH 端口和服务器安全组', s);
    }
    if (e is SocketException || e is SSHSocketError) {
      if (s.contains('Failed host lookup') || s.contains('No address associated')) {
        return NailongError('DNS_FAILED', '域名解析失败，请检查服务器地址', s);
      }
      if (s.contains('Connection refused')) {
        return NailongError('REFUSED', '服务器连接失败，请检查 IP 地址和 SSH 端口', s);
      }
      if (s.contains('Network is unreachable') || s.contains('No route to host')) {
        return NailongError('NETWORK', '网络不可达，请检查手机网络或服务器地址', s);
      }
      return NailongError('NETWORK', '服务器连接失败，请检查 IP 地址和 SSH 端口', s);
    }
    if (e is SSHHandshakeError) {
      return NailongError('HANDSHAKE', 'SSH 握手失败，服务器可能不支持当前加密算法', s);
    }
    if (e is SSHDisconnectError || s.contains('Connection closed') || s.contains('disconnect')) {
      return NailongError('DISCONNECTED', '连接被服务器断开，请稍后重试', s);
    }
    return NailongError('SSH_ERROR', '连接失败：${s.length > 120 ? s.substring(0, 120) : s}', s);
  }
}

/// 安装器错误码 → 中文提示。
const installerHints = <String, String>{
  'PRECHECK_FAILED': '服务器环境不满足部署条件',
  'DOCKER_SOURCE_FAILED': '无法访问 Docker 软件源，可在「下载加速」里添加可信的 Docker 软件源镜像',
  'APT_FAILED': '软件包安装失败，请检查服务器网络',
  'DOCKER_FAILED': 'Docker 安装失败或无法启动',
  'IMAGE_PULL_FAILED': 'Docker 镜像下载失败，请在「下载加速」里添加可信的镜像加速器后继续部署',
  'ASTRBOT_FAILED': 'AstrBot 启动失败',
  'NAPCAT_FAILED': 'NapCat 启动失败',
  'ONEBOT_FAILED': 'OneBot 连接配置失败',
  'AGENT_FAILED': '奶龙 Agent 启动失败',
  'AGENT_DEPS_FAILED': 'Agent 依赖下载失败，可在「下载加速」里添加可信的 PyPI 镜像',
  'PORT_CONFLICT': '端口冲突，没有可用端口',
  'VERIFY_FAILED': '服务验证未通过',
  'CANCELLED': '部署已取消，已完成的部分会保留，可以继续部署',
  'BUSY': '服务器上已有部署任务在运行',
  'TIMEOUT': '服务器执行超时',
};
