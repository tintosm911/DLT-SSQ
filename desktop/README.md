# 🖥️ 桌面版 (Tauri 壳 + Python sidecar)

把 Web GUI 的 9 个 Tab 包成原生 Windows 应用 —— 双击即用, 不用开终端。

## 架构

```
┌──────────────────────────────────────────────┐
│  Lottery分析工具.exe  (Tauri, ~5-10MB)        │
│    ├─ 启动 Python sidecar (Flask 后端)         │
│    │    └─ 动态端口 (系统分配, 避免冲突)        │
│    ├─ 等待端口就绪 (最多 40 秒)               │
│    └─ WebView 加载 http://127.0.0.1:<port>/   │
│         └─ 复用现有 9 个 Tab, 业务代码零改动    │
└──────────────────────────────────────────────┘
```

**为什么用 Tauri 而不是 Electron**: 体积小一个数量级 (5-10MB vs 100MB+),
内存占用低, 用系统 WebView2 (Windows 10/11 自带)。

## 开发

```powershell
cd desktop
npm install          # 首次
npm run tauri dev    # 开发模式 (带热重载)
```

## 打包

```powershell
# ⚠ CARGO_TARGET_DIR 必须放 C 盘 —— D 盘是 USB 外接 SSD, 有大文件写入损坏的 bug
$env:CARGO_TARGET_DIR = 'C:\cargo_target\lottery'
npm run tauri build
```

产物:
- `desktop/src-tauri/target/release/lottery-desktop.exe` (免安装)
- `desktop/src-tauri/target/release/bundle/nsis/*.exe` (安装包)

## 运行时要求

| 组件 | 要求 | 说明 |
|---|---|---|
| Python | 3.10+ | 必须能在 PATH 找到, 或设 `LOTTERY_PYTHON` |
| Python 依赖 | `pip install -r requirements-ci.txt` | pandas/numpy/scipy/matplotlib/flask |
| WebView2 | Windows 10/11 自带 | 缺失时运行 `tauri` 会提示安装 |

**自定义 Python 路径**:
```powershell
$env:LOTTERY_PYTHON = 'C:\Python314\python.exe'
```

## 已知限制

1. **不是完全独立 exe** —— 需要本机有 Python。彻底打包 (含 Python 解释器, 15-40MB)
   需要 `pyinstaller` + `tauri sidecar`, 见 `docs/desktop-packaging.md`
2. **首次启动慢** —— 加载 Python + 依赖, 3-10 秒 (之后秒开)
3. **端口冲突** —— 已用系统分配端口自动规避

## 目录

```
desktop/
├── index.html              加载页 (转场 + 错误提示)
├── package.json
├── vite.config.js
└── src-tauri/
    ├── Cargo.toml
    ├── tauri.conf.json
    ├── capabilities/default.json
    ├── icons/              图标 (scripts/make_icon.py 生成)
    └── src/
        ├── main.rs
        └── lib.rs          核心: sidecar 启动 / 端口探测 / 清理
```
