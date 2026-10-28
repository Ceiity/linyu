import 'package:material_ui/material_ui.dart';

ThemeData buildTheme(ColorScheme scheme, {bool pureBlack = false}) {
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
  return base.copyWith(
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
  Color get success => brightness == Brightness.dark ? const Color(0xFF4ADE80) : const Color(0xFF16A34A);
  Color get warning => brightness == Brightness.dark ? const Color(0xFFFBBF24) : const Color(0xFFD97706);
}

const brandYellow = 0xFFFFC83D;

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
  if (seedColor == brandYellow) {
    // 奶龙黄：亮黄色按钮 + 深色文字，浅色容器
    light = light.copyWith(
      primary: const Color(0xFFFFC83D),
      onPrimary: const Color(0xFF2B2100),
      primaryContainer: const Color(0xFFFFF4D6),
      onPrimaryContainer: const Color(0xFF3A2E00),
    );
    dark = dark.copyWith(
      primary: const Color(0xFFFFC83D),
      onPrimary: const Color(0xFF2B2100),
      primaryContainer: const Color(0xFF4A3B00),
      onPrimaryContainer: const Color(0xFFFFE08A),
    );
  }
  return (light, dark);
}
