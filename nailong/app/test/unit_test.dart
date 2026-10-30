import 'dart:convert';
import 'dart:typed_data';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nailong/core/errors.dart';
import 'package:nailong/core/keys.dart';
import 'package:nailong/core/ssh.dart';
import 'package:nailong/core/store.dart';

void main() {
  test('设备密钥：公钥格式符合服务器白名单，私钥可被解析', () {
    final k = DeviceKey.generate('nailong:nl-test0001');
    expect(RegExp(r'^ssh-ed25519 [A-Za-z0-9+/]{68}={0,2}$').hasMatch(k.publicLine), isTrue);
    final pairs = SSHKeyPair.fromPem(k.privatePem);
    expect(pairs.single.type, 'ssh-ed25519');
    final pub = base64.encode(pairs.single.toPublicKey().encode());
    expect(k.publicLine, 'ssh-ed25519 $pub');
  });

  test('主机指纹格式与 ssh-keygen 一致', () {
    final text = Uint8List.fromList(utf8.encode('SHA256:7RWDvIkD/pdOWCZ+CvfNiFqosk62YP/2GUtz8itVf6Y'));
    expect(formatFingerprint(text), 'SHA256:7RWDvIkD/pdOWCZ+CvfNiFqosk62YP/2GUtz8itVf6Y');
    final raw = Uint8List.fromList(List.generate(32, (i) => i));
    expect(formatFingerprint(raw), startsWith('SHA256:'));
    expect(formatFingerprint(raw).contains('='), isFalse);
  });

  test('下载源：内置国内源 + 用户源 + 官方兜底', () {
    final s = SourceSettings(pypi: ['https://pypi.example.com/simple'], registries: ['mirror.example.com']);
    final m = s.forInstaller();
    final pypi = m['pypi'] as List;
    expect(pypi.first, 'https://pypi.example.com/simple'); // 用户的排最前
    expect(pypi, containsAll(builtinPypi));
    expect(pypi.last, 'https://pypi.org/simple'); // 官方兜底在最后
    expect(m['docker_apt'], containsAll([...builtinDockerApt, 'https://download.docker.com']));
    final regs = m['registries'] as List;
    expect(regs.first, 'mirror.example.com');
    expect(regs, containsAll(builtinRegistries));
    expect(regs.toSet().length, regs.length); // 无重复
    expect(SourceSettings().forInstaller()['registries'], builtinRegistries);
  });

  test('错误提示是中文', () {
    expect(NailongError.fromSsh(SSHAuthFailError('x')).message, contains('密码错误'));
    expect(installerHints['IMAGE_PULL_FAILED'], contains('镜像'));
  });
}
