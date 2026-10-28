import 'package:flutter_test/flutter_test.dart';
import 'package:linyu_app/core/api.dart';

void main() {
  test('只填 IP 时优先探测 7070 端口', () {
    final c = panelCandidates('1.2.3.4');
    expect(c.first, 'http://1.2.3.4:7070');
    expect(c, contains('http://1.2.3.4:7079'));
    expect(c.any((e) => e.startsWith('https://')), isFalse);
  });

  test('带端口时直接使用', () {
    expect(panelCandidates('1.2.3.4:7071').first, 'http://1.2.3.4:7071');
    expect(panelCandidates('http://1.2.3.4:8080/').first, 'http://1.2.3.4:8080');
  });

  test('域名会额外尝试 HTTPS', () {
    final c = panelCandidates('panel.example.com');
    expect(c.first, 'http://panel.example.com:7070');
    expect(c, contains('https://panel.example.com'));
    expect(panelCandidates('https://panel.example.com').first, 'https://panel.example.com');
  });

  test('非法输入', () {
    expect(panelCandidates(''), isEmpty);
    expect(panelCandidates('   '), isEmpty);
  });
}
