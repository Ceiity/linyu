淋雨扣字手 C++ 重构分类版

本次修改属于第一阶段结构重构：
- 保留原有功能，不删除 AI、NapCat、QQ 头像、词库、发送、音效等逻辑。
- 不重写 UI，不改变原发送行为。
- main.cpp 从 4560 行拆到约 100 行。
- 原始大文件已保留为 main_original_before_refactor.cpp，方便对照和回滚。
- 分类文件使用 .inc 形式，由 main.cpp 按原代码顺序 include，仍然是单编译单元。

为什么先用 .inc：
- 原项目大量 static 函数和全局状态互相调用，如果直接拆成多个 .cpp/.h，很容易出现链接错误和声明混乱。
- 先用 .inc 可以最大限度保留行为，同时把代码按功能分类，后面再逐步升级成真正模块。

当前目录分类：
- core/：控件 ID、Settings、AppState、全局状态、基础常量。
- utils/：路径、输入法布局、字符串、编码、JSON、日志文本处理。
- network/：WinHTTP、QQ 头像请求、NapCat WebSocket、DeepSeek HTTP 调用。
- sender/：文本处理、拼音转换、SendInput、发送线程。
- ui/：UI 绘制、控件创建、窗口过程。
- config/：INI 配置读写、默认配置、保存、加载、重置。
- features/sound/：机械键盘音效。
- features/ai/：AI 生成文本逻辑。
- features/napcat/：NapCat 管理、脚本、日志、端口、二维码。
- features/library_sender.inc：词库管理、发送入口、QQ 头像预览流程。

编译：
- 原 build_cpp.ps1 仍然编译 main.cpp。
- main.cpp 会自动包含各个分类 .inc 文件。
