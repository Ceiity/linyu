import 'package:dynamic_color/dynamic_color.dart';
import 'package:flutter/services.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:material_ui/material_ui.dart';

import 'core/store.dart';
import 'pages/deploy_page.dart';
import 'pages/home_shell.dart';
import 'pages/welcome_page.dart';
import 'ui/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  FlutterForegroundTask.initCommunicationPort();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  final store = AppStore();
  await store.load();
  runApp(StoreScope(store: store, child: const NailongApp()));
}

class NailongApp extends StatelessWidget {
  const NailongApp({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    return DynamicColorBuilder(
      builder: (lightDynamic, darkDynamic) {
        var (light, dark) = appSchemes(s.seedColor);
        if (s.dynamicColor && lightDynamic != null && darkDynamic != null) {
          light = lightDynamic.harmonized();
          dark = darkDynamic.harmonized();
        }
        return MaterialApp(
          title: '奶龙',
          debugShowCheckedModeBanner: false,
          themeMode: s.themeMode,
          theme: buildTheme(light, look: s.buttonLook),
          darkTheme: buildTheme(dark, look: s.buttonLook),
          home: s.pending != null
              // App 被系统回收后重新打开：自动回到部署页，接上服务器上正在进行的部署
              ? DeployPage(
                  key: const ValueKey('resume-deploy'),
                  target: s.pending!.target,
                  savePassword: s.pending!.savePassword,
                  resume: true,
                )
              : (s.current == null ? const WelcomePage() : HomeShell(key: ValueKey(s.currentId))),
        );
      },
    );
  }
}
