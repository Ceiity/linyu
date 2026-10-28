import 'package:material_ui/material_ui.dart';

import '../core/connection.dart';

class ConnScope extends InheritedNotifier<ServerConnection> {
  const ConnScope({super.key, required ServerConnection conn, required super.child}) : super(notifier: conn);

  static ServerConnection of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<ConnScope>()!.notifier!;

  static ServerConnection? maybeOf(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<ConnScope>()?.widget as ConnScope?)?.notifier;
}

/// 从首页打开的二级页面也要能拿到当前连接。
Future<T?> pushPage<T>(BuildContext context, Widget page) {
  final conn = ConnScope.maybeOf(context);
  return Navigator.of(context).push<T>(
    MaterialPageRoute(
      builder: (_) => conn == null ? page : ConnScope(conn: conn, child: page),
    ),
  );
}
