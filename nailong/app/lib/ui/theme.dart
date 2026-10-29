import 'package:material_ui/material_ui.dart';

/// 主按钮风格：浅色渐变（白→浅灰，深色文字）或黑色渐变（石墨→黑，白色文字）。
enum ButtonLook { light, dark }

ThemeData buildTheme(ColorScheme scheme, {bool pureBlack = false, ButtonLook look = ButtonLook.light}) {
  var cs = scheme;
  if (pureBlack && cs.brightness == Brightness.dark) {
    cs = cs.copyWith(
      surface: Colors.black,
      surfaceContainerLowest: Colors.black,
      surfaceContainerLow: const Color(0xFF0B0B0C),
      surfaceContainer: const Color(0xFF141416),
      surfaceContainerHigh: const Color(0xFF1C1C1E),
      surfaceContainerHighest: const Color(0xFF242427),
    );
  }
  final base = ThemeData(colorScheme: cs, useMaterial3: true);
  final dark = cs.brightness == Brightness.dark;
  // 深色模式下“浅色渐变”按钮用浅灰渐变，“黑色渐变”用更亮一点的石墨，保证可见
  final useDarkLook = look == ButtonLook.dark;
  final grad = useDarkLook
      ? (dark ? const [Color(0xFF5A5E66), Color(0xFF34373D)] : const [Color(0xFF45484F), Color(0xFF17181B)])
      : (dark ? const [Color(0xFFF2F3F5), Color(0xFFC9CCD2)] : const [Color(0xFFFFFFFF), Color(0xFFDDE0E5)]);
  final fg = useDarkLook ? Colors.white : const Color(0xFF1C1E21);
  final edge = useDarkLook ? Colors.transparent : (dark ? const Color(0x00000000) : const Color(0xFFCDD1D7));
  final gradientButton = ButtonStyle(
    backgroundColor: const WidgetStatePropertyAll(Colors.transparent),
    shadowColor: const WidgetStatePropertyAll(Colors.transparent),
    surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
    elevation: const WidgetStatePropertyAll(0),
    foregroundColor: WidgetStateProperty.resolveWith(
      (s) => s.contains(WidgetState.disabled) ? cs.onSurface.withValues(alpha: 0.38) : fg,
    ),
    overlayColor: WidgetStatePropertyAll(fg.withValues(alpha: 0.08)),
    padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 22, vertical: 14)),
    shape: WidgetStatePropertyAll(RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
    backgroundBuilder: (context, states, child) {
      final off = states.contains(WidgetState.disabled);
      return DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: off ? [cs.onSurface.withValues(alpha: 0.10), cs.onSurface.withValues(alpha: 0.10)] : grad,
          ),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: off ? Colors.transparent : edge),
          boxShadow: off || dark
              ? null
              : [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: useDarkLook ? 0.22 : 0.08),
                    blurRadius: 10,
                    offset: const Offset(0, 3),
                  ),
                ],
        ),
        child: child,
      );
    },
  );
  return base.copyWith(
    filledButtonTheme: FilledButtonThemeData(style: gradientButton),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: useDarkLook ? const Color(0xFF2A2C31) : (dark ? const Color(0xFFE8EAED) : Colors.white),
      foregroundColor: useDarkLook ? Colors.white : const Color(0xFF1C1E21),
      elevation: 3,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(color: useDarkLook ? Colors.transparent : const Color(0xFFCDD1D7)),
      ),
    ),
    scaffoldBackgroundColor: cs.surface,
    appBarTheme: AppBarTheme(
      backgroundColor: cs.surface,
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      centerTitle: false,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: cs.surfaceContainer,
      indicatorColor: cs.secondaryContainer,
      elevation: 0,
      height: 68,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (s) => TextStyle(
          fontSize: 12,
          fontWeight: s.contains(WidgetState.selected) ? FontWeight.w700 : FontWeight.w500,
          color: s.contains(WidgetState.selected) ? cs.onSurface : cs.onSurfaceVariant,
        ),
      ),
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: cs.surfaceContainer,
      indicatorColor: cs.secondaryContainer,
    ),
    cardTheme: CardThemeData(
      color: cs.surfaceContainer,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: cs.surfaceContainerHighest.withValues(alpha: 0.6),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: cs.surfaceContainerLow,
      showDragHandle: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    ),
    dialogTheme: DialogThemeData(backgroundColor: cs.surfaceContainerHigh),
    listTileTheme: const ListTileThemeData(contentPadding: EdgeInsets.symmetric(horizontal: 16)),
  );
}

extension StatusColors on ColorScheme {
  /// 强调色文字：亮黄等浅主题色在白底上看不清，浅色模式下用加深的同色系。
  Color get accentText => brightness == Brightness.light && primary.computeLuminance() > 0.45
      ? Color.lerp(primary, Colors.black, 0.45)!
      : primary;

  Color get success => brightness == Brightness.dark ? const Color(0xFF4ADE80) : const Color(0xFF16A34A);
  Color get warning => brightness == Brightness.dark ? const Color(0xFFFBBF24) : const Color(0xFFD97706);
}

const brandGraphite = 0xFF2F3237;

/// 浅色中性背景（白 / 浅灰卡片），主题色只用于按钮、开关等强调元素。
(ColorScheme, ColorScheme) appSchemes(int seedColor) {
  final seed = Color(seedColor);
  var light = ColorScheme.fromSeed(seedColor: seed, dynamicSchemeVariant: DynamicSchemeVariant.tonalSpot);
  var dark = ColorScheme.fromSeed(
    seedColor: seed,
    brightness: Brightness.dark,
    dynamicSchemeVariant: DynamicSchemeVariant.tonalSpot,
  );
  light = light.copyWith(
    surface: const Color(0xFFF6F7F9),
    onSurface: const Color(0xFF1C1E21),
    onSurfaceVariant: const Color(0xFF5F6368),
    surfaceContainerLowest: const Color(0xFFFFFFFF),
    surfaceContainerLow: const Color(0xFFFAFBFC),
    surfaceContainer: const Color(0xFFFFFFFF),
    surfaceContainerHigh: const Color(0xFFF0F1F4),
    surfaceContainerHighest: const Color(0xFFE8EAED),
    secondaryContainer: const Color(0xFFEDEFF2),
    onSecondaryContainer: const Color(0xFF1C1E21),
    outline: const Color(0xFF9AA0A6),
    outlineVariant: const Color(0xFFDADCE0),
  );
  dark = dark.copyWith(
    surface: const Color(0xFF121315),
    onSurface: const Color(0xFFE8EAED),
    onSurfaceVariant: const Color(0xFFA8ADB4),
    surfaceContainerLowest: const Color(0xFF0D0E10),
    surfaceContainerLow: const Color(0xFF17181B),
    surfaceContainer: const Color(0xFF1C1E21),
    surfaceContainerHigh: const Color(0xFF25272B),
    surfaceContainerHighest: const Color(0xFF2E3135),
    secondaryContainer: const Color(0xFF2E3135),
    onSecondaryContainer: const Color(0xFFE8EAED),
    outline: const Color(0xFF7C8187),
    outlineVariant: const Color(0xFF3A3D42),
  );
  if (seedColor == brandGraphite) {
    // 默认主题：石墨灰作为强调色（开关、进度、选中态），不带任何黄色
    light = light.copyWith(
      primary: const Color(0xFF2F3237),
      onPrimary: Colors.white,
      primaryContainer: const Color(0xFFE9EBEF),
      onPrimaryContainer: const Color(0xFF1C1E21),
      tertiary: const Color(0xFF8A9099),
    );
    dark = dark.copyWith(
      primary: const Color(0xFFE3E5E9),
      onPrimary: const Color(0xFF17181B),
      primaryContainer: const Color(0xFF34373D),
      onPrimaryContainer: const Color(0xFFE8EAED),
      tertiary: const Color(0xFF8A9099),
    );
  }
  return (light, dark);
}
