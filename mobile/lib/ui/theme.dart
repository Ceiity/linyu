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
