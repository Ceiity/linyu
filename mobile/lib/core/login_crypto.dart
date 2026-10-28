import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:pointycastle/export.dart';

/// 与面板前端 buildEncryptedLogin 完全一致：
/// AES-256-GCM 加密账号密码，RSA-OAEP(SHA-256) 包裹 AES 密钥。
Map<String, dynamic> buildEncryptedLogin({
  required Map<String, dynamic> challenge,
  required String username,
  required String password,
}) {
  final rnd = Random.secure();
  Uint8List randomBytes(int n) => Uint8List.fromList(List<int>.generate(n, (_) => rnd.nextInt(256)));

  final id = challenge['id'].toString();
  final nonce = challenge['nonce'].toString();
  final issued = challenge['issued_at'].toString();
  final aadText = '$id.$nonce.$issued';
  final aad = Uint8List.fromList(utf8.encode(aadText));

  final payload = Uint8List.fromList(
    utf8.encode(
      jsonEncode({
        'username': username,
        'password': password,
        'challenge_id': id,
        'nonce': nonce,
        'ts': DateTime.now().millisecondsSinceEpoch ~/ 1000,
      }),
    ),
  );

  final aesKey = randomBytes(32);
  final iv = randomBytes(12);
  final gcm = GCMBlockCipher(AESEngine())..init(true, AEADParameters(KeyParameter(aesKey), 128, iv, aad));
  final cipher = gcm.process(payload);

  final rsa = OAEPEncoding.withSHA256(RSAEngine())
    ..init(
      true,
      PublicKeyParameter<RSAPublicKey>(
        RSAPublicKey(_b64uToBigInt(challenge['rsa_n'].toString()), _b64uToBigInt(challenge['rsa_e'].toString())),
      ),
    );
  final wrapped = rsa.process(aesKey);

  final digest = SHA256Digest().process(Uint8List.fromList([...aad, 46, ...cipher]));

  return {
    'mode': 'crypto',
    'encrypted': {
      'challenge_id': id,
      'aad': aadText,
      'iv': base64Encode(iv),
      'key': base64Encode(wrapped),
      'ciphertext': base64Encode(cipher),
      'digest': base64Encode(digest),
    },
  };
}

BigInt _b64uToBigInt(String s) {
  var t = s.replaceAll('-', '+').replaceAll('_', '/');
  while (t.length % 4 != 0) {
    t += '=';
  }
  final bytes = base64Decode(t);
  var result = BigInt.zero;
  for (final b in bytes) {
    result = (result << 8) | BigInt.from(b);
  }
  return result;
}
