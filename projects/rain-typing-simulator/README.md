# Rain Typing Simulator

&#x4E2D;&#x6587;&#x540D;&#xFF1A;&#x6DCB;&#x96E8;&#x6A21;&#x62DF;&#x6253;&#x5B57;

&#x8FD9;&#x662F;&#x4E00;&#x4E2A; Windows C++ &#x684C;&#x9762;&#x7A0B;&#x5E8F;&#x9879;&#x76EE;&#xFF0C;&#x5305;&#x542B;&#x5DF2;&#x7ECF;&#x7F16;&#x8BD1;&#x597D;&#x7684;&#x53EF;&#x6267;&#x884C;&#x6587;&#x4EF6;&#x548C;&#x5B8C;&#x6574;&#x6E90;&#x7801;&#x3002;

## &#x5728;&#x7EBF;&#x9875;&#x9762;

- &#x9879;&#x76EE;&#x9875;&#xFF1A;https://ceiity.github.io/linyu/projects/rain-typing-simulator/
- &#x6E90;&#x7801;&#x76EE;&#x5F55;&#xFF1A;https://ceiity.github.io/linyu/projects/rain-typing-simulator/source/
- &#x6253;&#x5305;&#x6559;&#x7A0B;&#xFF1A;https://ceiity.github.io/linyu/projects/rain-typing-simulator/build.html

## &#x76EE;&#x5F55;&#x5185;&#x5BB9;

- `RainTypingSimulator.exe`&#xFF1A;&#x5DF2;&#x7F16;&#x8BD1;&#x597D;&#x7684; Windows &#x7A0B;&#x5E8F;
- `source/`&#xFF1A;C++ &#x6E90;&#x7801;&#x76EE;&#x5F55;
- `source/build_cpp.ps1`&#xFF1A;Windows PowerShell &#x81EA;&#x52A8;&#x7F16;&#x8BD1;&#x811A;&#x672C;
- `build.html`&#xFF1A;&#x7F51;&#x9875;&#x7248;&#x6253;&#x5305;&#x6559;&#x7A0B;
- `BUILD.md`&#xFF1A;Markdown &#x7248;&#x6253;&#x5305;&#x6559;&#x7A0B;

## &#x5FEB;&#x901F;&#x6253;&#x5305;

&#x5728; Windows &#x7535;&#x8111;&#x6253;&#x5F00; PowerShell&#xFF1A;

```powershell
winget install MartinStorsjo.LLVM-MinGW.UCRT
cd source
Set-ExecutionPolicy -Scope Process Bypass -Force
.\build_cpp.ps1
```

&#x7F16;&#x8BD1;&#x5B8C;&#x6210;&#x540E;&#xFF0C;&#x7A0B;&#x5E8F;&#x4F1A;&#x751F;&#x6210;&#x5230;&#xFF1A;

```text
outputs/&#x6DCB;&#x96E8;.exe
```

&#x5982;&#x679C;&#x4E0D;&#x60F3;&#x81EA;&#x5DF1;&#x6253;&#x5305;&#xFF0C;&#x53EF;&#x4EE5;&#x76F4;&#x63A5;&#x4E0B;&#x8F7D;&#x9879;&#x76EE;&#x9875;&#x91CC;&#x7684; `RainTypingSimulator.exe`&#x3002;
