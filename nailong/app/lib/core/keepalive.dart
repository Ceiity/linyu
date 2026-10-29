import 'package:flutter_foreground_task/flutter_foreground_task.dart';

/// 部署期间的前台服务（通知栏常驻）。
/// 国产手机系统会在 App 切到后台几秒后直接杀进程，前台服务能显著降低被杀的概率。
/// 这只是“尽力而为”：失败不影响部署（部署本身在服务器上独立运行）。
@pragma('vm:entry-point')
void keepAliveCallback() {
  FlutterForegroundTask.setTaskHandler(_IdleHandler());
}

class _IdleHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {}

  @override
  void onRepeatEvent(DateTime timestamp) {}

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {}
}

class DeployKeepAlive {
  static bool _inited = false;

  static void _init() {
    if (_inited) return;
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'nailong_deploy',
        channelName: '奶龙部署',
        channelDescription: '部署服务器期间保持连接，避免被系统回收',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(showNotification: false, playSound: false),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.nothing(),
        allowWakeLock: true,
        allowWifiLock: true,
      ),
    );
    _inited = true;
  }

  static Future<void> start(String text) async {
    try {
      _init();
      if (await FlutterForegroundTask.checkNotificationPermission() != NotificationPermission.granted) {
        await FlutterForegroundTask.requestNotificationPermission();
      }
      if (await FlutterForegroundTask.isRunningService) {
        await FlutterForegroundTask.updateService(notificationTitle: '奶龙正在部署服务器', notificationText: text);
      } else {
        await FlutterForegroundTask.startService(
          serviceId: 7401,
          serviceTypes: [ForegroundServiceTypes.dataSync],
          notificationTitle: '奶龙正在部署服务器',
          notificationText: text,
          callback: keepAliveCallback,
        );
      }
    } catch (_) {}
  }

  static Future<void> update(String text) async {
    try {
      if (await FlutterForegroundTask.isRunningService) {
        await FlutterForegroundTask.updateService(notificationTitle: '奶龙正在部署服务器', notificationText: text);
      }
    } catch (_) {}
  }

  static Future<void> stop() async {
    try {
      if (await FlutterForegroundTask.isRunningService) await FlutterForegroundTask.stopService();
    } catch (_) {}
  }
}
