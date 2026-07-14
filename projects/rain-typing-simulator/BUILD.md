# Rain Typing Simulator &#x6253;&#x5305;&#x6559;&#x7A0B;

&#x672C;&#x9879;&#x76EE;&#x662F; Windows C++ &#x684C;&#x9762;&#x7A0B;&#x5E8F;&#xFF0C;&#x4F7F;&#x7528; `clang++` &#x548C; `windres` &#x7F16;&#x8BD1;&#x3002;

## &#x4E00;&#x3001;&#x51C6;&#x5907;&#x73AF;&#x5883;

&#x9700;&#x8981;&#x4E00;&#x53F0; Windows &#x7535;&#x8111;&#xFF0C;&#x5E76;&#x5B89;&#x88C5;&#xFF1A;

1. PowerShell
2. winget
3. LLVM-MinGW UCRT

&#x5B89;&#x88C5; LLVM-MinGW&#xFF1A;

```powershell
winget install MartinStorsjo.LLVM-MinGW.UCRT
```

&#x5B89;&#x88C5;&#x5B8C;&#x6210;&#x540E;&#xFF0C;&#x91CD;&#x65B0;&#x6253;&#x5F00; PowerShell&#x3002;

## &#x4E8C;&#x3001;&#x4E0B;&#x8F7D;&#x6E90;&#x7801;

&#x53EF;&#x4EE5;&#x76F4;&#x63A5;&#x4ECE; GitHub &#x4E0B;&#x8F7D;&#x6574;&#x4E2A;&#x4ED3;&#x5E93;&#xFF0C;&#x4E5F;&#x53EF;&#x4EE5;&#x4E0B;&#x8F7D;&#x6E90;&#x7801;&#x76EE;&#x5F55;&#xFF1A;

```text
projects/rain-typing-simulator/source/
```

## &#x4E09;&#x3001;&#x5F00;&#x59CB;&#x7F16;&#x8BD1;

&#x8FDB;&#x5165;&#x6E90;&#x7801;&#x76EE;&#x5F55;&#xFF1A;

```powershell
cd projects\rain-typing-simulator\source
```

&#x5141;&#x8BB8;&#x5F53;&#x524D; PowerShell &#x7A97;&#x53E3;&#x6267;&#x884C;&#x811A;&#x672C;&#xFF1A;

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

&#x6267;&#x884C;&#x6253;&#x5305;&#x811A;&#x672C;&#xFF1A;

```powershell
.\build_cpp.ps1
```

## &#x56DB;&#x3001;&#x8F93;&#x51FA;&#x4F4D;&#x7F6E;

&#x6210;&#x529F;&#x540E;&#x4F1A;&#x751F;&#x6210;&#xFF1A;

```text
projects/rain-typing-simulator/outputs/&#x6DCB;&#x96E8;.exe
```

## &#x4E94;&#x3001;&#x5E38;&#x89C1;&#x95EE;&#x9898;

### 1. &#x63D0;&#x793A;&#x627E;&#x4E0D;&#x5230; clang++ &#x6216; windres

&#x8BF4;&#x660E; LLVM-MinGW &#x6CA1;&#x88C5;&#x597D;&#xFF0C;&#x91CD;&#x65B0;&#x6267;&#x884C;&#xFF1A;

```powershell
winget install MartinStorsjo.LLVM-MinGW.UCRT
```

&#x5982;&#x679C;&#x8FD8;&#x662F;&#x4E0D;&#x884C;&#xFF0C;&#x5173;&#x95ED; PowerShell &#x540E;&#x91CD;&#x65B0;&#x6253;&#x5F00;&#x3002;

### 2. &#x63D0;&#x793A;&#x7981;&#x6B62;&#x8FD0;&#x884C;&#x811A;&#x672C;

&#x6267;&#x884C;&#xFF1A;

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

&#x7136;&#x540E;&#x91CD;&#x65B0;&#x8FD0;&#x884C;&#xFF1A;

```powershell
.\build_cpp.ps1
```

### 3. &#x7F16;&#x8BD1;&#x51FA;&#x6765;&#x7684; exe &#x88AB;&#x6D4F;&#x89C8;&#x5668;&#x6216;&#x6740;&#x6BD2;&#x8F6F;&#x4EF6;&#x63D0;&#x793A;

&#x8FD9;&#x662F;&#x4E2A;&#x4EBA;&#x7F16;&#x8BD1;&#x7684; Windows &#x7A0B;&#x5E8F;&#x5E38;&#x89C1;&#x60C5;&#x51B5;&#x3002;&#x53EF;&#x4EE5;&#x7ED9; exe &#x505A;&#x4EE3;&#x7801;&#x7B7E;&#x540D;&#xFF0C;&#x6216;&#x8005;&#x5728;&#x4E0B;&#x8F7D;&#x63D0;&#x793A;&#x91CC;&#x9009;&#x62E9;&#x4FDD;&#x7559;&#x3002;

## &#x516D;&#x3001;&#x624B;&#x52A8;&#x7F16;&#x8BD1;&#x547D;&#x4EE4;

&#x5982;&#x679C;&#x4E0D;&#x4F7F;&#x7528;&#x811A;&#x672C;&#xFF0C;&#x53EF;&#x4EE5;&#x53C2;&#x8003;&#xFF1A;

```powershell
windres resource.rc -O coff -o resource.o
clang++ -std=c++17 -O2 -municode -mwindows -static main.cpp resource.o -o ..\outputs\&#x6DCB;&#x96E8;.exe -lcomctl32 -lpsapi -lwinmm -lshell32 -lcomdlg32 -ldwmapi -lgdi32 -lgdiplus -lole32 -ladvapi32 -lwinhttp -liphlpapi -limm32
```
