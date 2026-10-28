import 'package:dynamic_color/dynamic_color.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import 'core/store.dart';
import 'pages/home_shell.dart';
import 'pages/welcome_page.dart';
import 'ui/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
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
          theme: buildTheme(light),
          darkTheme: buildTheme(dark),
          home: s.current == null ? const WelcomePage() : HomeShell(key: ValueKey(s.currentId)),
        );
      },
    );
  }
}
