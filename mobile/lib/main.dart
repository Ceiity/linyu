import 'package:dynamic_color/dynamic_color.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

import 'core/app_state.dart';
import 'pages/home_shell.dart';
import 'pages/login_page.dart';
import 'pages/server_page.dart';
import 'ui/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  final state = AppState();
  await state.load();
  runApp(AppScope(state: state, child: const LinyuApp()));
}

class LinyuApp extends StatelessWidget {
  const LinyuApp({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return DynamicColorBuilder(
      builder: (lightDynamic, darkDynamic) {
        final seed = Color(s.seedColor);
        var light = ColorScheme.fromSeed(seedColor: seed, dynamicSchemeVariant: DynamicSchemeVariant.fidelity);
        var dark = ColorScheme.fromSeed(
          seedColor: seed,
          brightness: Brightness.dark,
          dynamicSchemeVariant: DynamicSchemeVariant.fidelity,
        );
        if (s.dynamicColor && lightDynamic != null && darkDynamic != null) {
          light = lightDynamic.harmonized();
          dark = darkDynamic.harmonized();
        }
        return MaterialApp(
          title: '淋雨',
          debugShowCheckedModeBanner: false,
          themeMode: s.themeMode,
          theme: buildTheme(light),
          darkTheme: buildTheme(dark, pureBlack: s.pureBlack),
          home: const _Root(),
        );
      },
    );
  }
}

class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final Widget page;
    if (s.current == null) {
      page = const ServerPage(key: ValueKey('server'));
    } else if (!s.loggedIn) {
      page = LoginPage(key: ValueKey('login:${s.current!.baseUrl}'));
    } else {
      page = HomeShell(key: ValueKey('home:${s.current!.baseUrl}'));
    }
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 280),
      switchInCurve: Curves.easeOutCubic,
      transitionBuilder: (child, anim) => FadeTransition(
        opacity: anim,
        child: SlideTransition(
          position: Tween(begin: const Offset(0, 0.03), end: Offset.zero).animate(anim),
          child: child,
        ),
      ),
      child: page,
    );
  }
}
