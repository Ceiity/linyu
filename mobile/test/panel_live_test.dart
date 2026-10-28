// 需要本地面板：PANEL_URL=http://127.0.0.1:7070 PANEL_USER=... PANEL_PASS=... flutter test test/panel_live_test.dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:linyu_app/core/api.dart';

void main() {
  final url = Platform.environment['PANEL_URL'];
  final skip = url == null ? '未设置 PANEL_URL' : null;

  test('自动发现、加密登录、带会话读写', () async {
    final host = Uri.parse(url!).host;
    final port = Uri.parse(url).port;
    final found = await discoverPanel(port == 7070 ? host : '$host:$port');
    expect(found?.baseUrl, url);

    final api = ApiClient(url);
    await expectLater(api.login('wrong', 'wrong'), throwsA(isA<ApiException>()));
    final token = await api.login(Platform.environment['PANEL_USER']!, Platform.environment['PANEL_PASS']!);
    expect(token, contains('.'));

    final me = await api.get('/api/me');
    expect(me['login'], isTrue);

    final saved = await api.post('/api/settings', {'theme_color': '#2563eb'});
    expect(saved['theme_color'], '#2563eb');

    final tasks = await api.get('/api/tasks');
    expect(tasks, isA<List>());

    api.token = 'bad.token';
    await expectLater(api.get('/api/me'), throwsA(predicate((e) => e is ApiException && e.unauthorized)));
  }, skip: skip);
}
