import 'dart:convert';
import 'dart:typed_data';

import 'package:dartssh2/dartssh2.dart';
import 'package:pinenacl/ed25519.dart' as nacl;

/// App 专属的 Ed25519 密钥：部署完成后写入服务器 authorized_keys，
/// 并被限制为只能转发到 Agent 端口（restrict + permitopen）。
class DeviceKey {
  final String privatePem;
  final String publicLine;

  DeviceKey(this.privatePem, this.publicLine);

  static DeviceKey generate(String comment) {
    final sk = nacl.SigningKey.generate();
    final pub = Uint8List.fromList(sk.verifyKey.asTypedList);
    final priv = Uint8List.fromList([...sk.seed.asTypedList, ...pub]);
    final pair = OpenSSHEd25519KeyPair(pub, priv, comment);
    final blob = _sshString(utf8.encode('ssh-ed25519')) + _sshString(pub);
    return DeviceKey(pair.toPem(), 'ssh-ed25519 ${base64.encode(blob)}');
  }

  /// SSH 线格式字符串：uint32 长度 + 内容。
  static List<int> _sshString(List<int> data) {
    final len = ByteData(4)..setUint32(0, data.length);
    return [...len.buffer.asUint8List(), ...data];
  }
}
