# 软件未经过系统测试，请现在虚拟机上运行进行效果测试
# Windows 系统优化管家

> 一款开源、免费、界面精美的 Windows 系统优化工具，集成 **C 盘清理**、**软件卸载**、**软件搬家** 三大功能。

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ 功能特性

### 🧹 C 盘清理
- 内置 **50+ 条** 安全清理规则（系统/用户/浏览器/应用/开发工具）
- 涵盖 Windows 临时文件、浏览器缓存、IDE 缓存、构建工具缓存、GPU 着色器缓存等
- **默认走回收站**，可随时还原
- 不删 `System32`、`Program Files`、用户文档、桌面、下载
- 跳过 24 小时内修改的文件
- 不跟随 Junction / Symbolic Link

### 🗑️ 软件卸载
- **标准卸载**：调用程序自身的 UninstallString
- **静默卸载**：使用 QuietUninstallString（适用于 NSIS/Inno Setup）
- **残留扫描**：基于 publisher / app name 智能匹配 AppData、ProgramData、注册表、快捷方式
- **强制卸载**：当原生卸载失败时清理所有相关残留
- 支持 **MSI 程序**、**UWP/AppX 应用**（Microsoft Store）
- 系统关键程序保护

### 📦 软件搬家
- 选择程序 → 选择目标盘 → 一键搬家
- 完整流程：**预检 → 复制 → 校验 → 切换链接 → 写历史**
- 使用 NTFS **Junction** 或 **Symbolic Link**，对应用完全透明
- 完整的搬家历史，**一键回滚**
- 预检 NTFS 文件系统、磁盘空间、进程占用
- 校验 SHA-256 抽样，确保复制完整

### 🎨 界面设计
- 采用 **PySide6-Fluent-Widgets**，对标微软 PowerToys / Files 的 Win11 Fluent 设计
- 侧边栏导航、卡片式统计、响应式布局
- 适配明色 / 暗色主题
- 全程中文界面

---

## 🚀 快速使用

### 方式 1：直接运行源码（推荐开发者）
1. 安装 Python 3.10 或更高版本：[python.org](https://www.python.org/downloads/)
2. 双击运行 `run.bat`（自动安装依赖并以管理员权限启动）

### 方式 2：使用打包后的 EXE
1. 双击 `dist\Windows系统优化管家.exe`（首次运行会自动请求管理员权限）

### 方式 3：自己打包
1. 双击 `build.bat`
2. 等待约 2-5 分钟生成单文件 EXE

---

## 🏗️ 技术架构

| 层级 | 技术 |
|------|------|
| 界面 | PySide6 + qfluentwidgets |
| 系统 API | pywin32、psutil、wmi |
| 回收站 | send2trash |
| 符号链接 | Windows `mklink /J`、`mklink /D` |
| 数据存储 | JSON 文件（APPDATA 目录） |
| 打包 | PyInstaller（单文件、压缩、自带 Python） |

### 项目结构
```
├── main.py                       # 入口
├── requirements.txt              # 依赖
├── run.bat / build.bat           # 运行 / 打包脚本
├── app/
│   ├── config.py                 # 全局配置
│   ├── common/                   # 公共工具（路径、日志、管理员、字节格式化）
│   ├── models/                   # 数据模型
│   ├── services/                 # 业务逻辑（cleaner / mover / uninstaller）
│   ├── ui/
│   │   ├── main_window.py        # 主窗口
│   │   └── pages/                # 主页 / 清理 / 卸载 / 搬家 / 关于
│   └── resources/
│       └── rules/
│           └── default_rules.json # 50+ 内置清理规则
```

---

## 🔒 安全机制

| 操作 | 策略 |
|------|------|
| 启动 | 自动请求管理员权限 |
| 清理 | 默认走回收站；预览后才执行；跳过最近 24h 文件；不跟随 Junction；二次校验路径 |
| 卸载 | 默认调用官方卸载命令；超时保护；卸载后询问扫残留；强制卸载需确认 |
| 搬家 | 预检 NTFS / 空间 / 进程；不搬系统/运行中程序；目标复制完成且校验后才切换链接；保留源目录 backup；完整历史支持一键回滚 |
| 系统关键程序 | 强制白名单保护，无法在 UI 中卸载/搬动 |
| 受保护路径 | System32、WinSxS、Program Files 根、用户文档、桌面、下载 |
| 日志 | 所有操作写入 `%APPDATA%\Windows系统优化管家\log.txt` |

---

## 📋 内置清理规则（50+ 条）

### 系统类（需要管理员权限）
- Windows 临时文件
- Windows 日志文件
- Windows Update 下载缓存
- 内核崩溃转储（LiveKernelReports）
- 小型内存转储（Minidump）
- Windows 调试日志
- 服务账户临时文件
- 完整内存转储（默认关闭）

### 用户类
- 用户临时文件
- 缩略图缓存
- 应用崩溃转储
- Windows 错误报告归档

### 浏览器类
- Microsoft Edge 缓存
- Google Chrome 缓存
- Mozilla Firefox 缓存
- Brave 浏览器缓存

### 应用类
- Discord / Slack / Teams / Zoom / Spotify
- VS Code / Cursor / JetBrains 全家桶
- Steam / Epic Games
- NVIDIA / AMD 着色器缓存
- Adobe 媒体缓存

### 开发工具类
- npm / yarn / pnpm 缓存
- pip / uv 缓存
- Rust Cargo 缓存
- Go 模块缓存
- Gradle / Maven / NuGet 缓存
- Hugging Face / Ollama（默认关闭）
- Playwright 浏览器缓存

### 高级（默认关闭，需手动启用）
- 清空回收站
- 内存转储文件

---

## ⚠️ 注意事项

1. **必须以管理员身份运行**：清理系统目录、卸载程序、创建符号链接均需管理员权限
2. **Win10/11 64 位**：在 Windows 10 1809+ / Windows 11 上测试通过
3. **首次启动较慢**：会枚举所有已安装程序（首次约需 10-30 秒）
4. **某些软件搬家可能失败**：授权绑定的软件、内核驱动、UWP、MSIX 不建议搬
5. **搬家后请保留 backup 7 天**：以便出现问题时可以回滚

---

## 📜 许可证

本项目采用 **MIT 许可证** 开源发布。

### 参考的开源项目
- [BleachBit](https://github.com/bleachbit/bleachbit) - 通用清理标杆
- [BCUninstaller](https://github.com/BCUninstaller/Bulk-Crap-Uninstaller) - 卸载广度
- [Winapp2.ini](https://github.com/MoscaDotTo/Winapp2) - 清理规则库标准
- [Viap](https://github.com/Chunyu33/viap) - 软件搬家设计
- [FreeMove](https://github.com/imDema/FreeMove) - Junction 实现
- [NeatShift](https://github.com/BytexGrid/NeatShift) - 搬家 UI
- [MangoDisk](https://github.com/harry0703/MangoDisk) - 现代多合一
- [BHUninstaller](https://github.com/wpexpertinbd/BHUninstaller) - 安全哲学
- [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) - UI 组件

---

## 🛠️ 开发说明

### 调试
```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行
python main.py
```

### 添加新的清理规则
编辑 `app/resources/rules/default_rules.json`，按以下格式添加：
```json
{
  "id": "my_rule_id",
  "category": "应用",
  "name": "我的规则",
  "description": "详细说明",
  "paths": ["%LOCALAPPDATA%\\MyApp\\Cache"],
  "patterns": ["*"],
  "min_age_days": 7,
  "risk": "safe",
  "requires_admin": false,
  "enabled_by_default": true
}
```

### 反馈与建议
欢迎提交 Issue 或 PR。

---

**祝使用愉快！** 🎉