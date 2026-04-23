## 仅录制视频（精简版）

这个目录只保留“录制桌面视频 + 可选麦克风录音 + 可选择保存目录 + 圆形悬浮按钮停止录制”功能。

### 依赖

- **Windows**
- **FFmpeg**：需要在 `PATH` 中能直接运行 `ffmpeg`
- Python：自带 `tkinter`（一般 Windows Python 自带）

### 安装（可选）

本目录 `requirements.txt` 目前为空：不依赖第三方 Python 包。

如果你希望用虚拟环境隔离（可选）：

```powershell
cd .\video-recorder-only
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 启动

#### 方式 A：在仓库根目录启动

```powershell
python .\video-recorder-only\recorder.py
```

#### 方式 B：进入目录后启动（推荐）

```powershell
cd .\video-recorder-only
python .\recorder.py
```

#### 方式 C：一键脚本（推荐）

```powershell
cd .\video-recorder-only
.\run.ps1
```

或双击 `run.bat`。

> 如果你第一次运行 `run.ps1` 被 PowerShell 拦截，可先执行（当前用户范围即可）：
>
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 输出文件

会保存到你选择的目录中：

- `recording_YYYYMMDD_HHMMSS.mp4`
- `ffmpeg_log.txt`

配置会保存到同目录下的 `recorder_config.json`（窗口大小位置、保存目录）。

### 常见问题

- **提示找不到 ffmpeg**：把 ffmpeg 加入系统 PATH，或重启终端后再试。
- **麦克风列表为空**：通常是 ffmpeg 无法枚举 dshow 设备；请确认 ffmpeg 版本支持 dshow，并检查系统隐私设置是否允许应用访问麦克风。

#### 双击 `run.bat` 后找不到 ffmpeg / 麦克风为空

从资源管理器双击启动时，有些机器会出现 PATH 与终端不同，导致程序找不到 `ffmpeg`。

现在程序支持在界面里直接选择 `ffmpeg.exe`：

- 点击设置卡片里的 **“FFmpeg → 选择…”**
- 选择你的 `ffmpeg.exe`（例如 `D:\\AiSoft\\ffmpeg\\bin\\ffmpeg.exe`）
- 再点 **“刷新麦克风”** 即可恢复列表

选择会保存到 `recorder_config.json`，下次双击也能正常识别。

### 打包分发（你选择：文件夹分发 / onedir）

本目录提供 `build.ps1`（推荐）与 `build.bat`，使用 **PyInstaller** 生成：

- `dist/录屏助手/`（内含 `录屏助手.exe` 与依赖文件）

#### 1) 安装打包依赖

```powershell
cd .\video-recorder-only
python -m pip install -r .\requirements-dev.txt
```

#### 2) 执行打包

```powershell
.\build.ps1
```

或双击 `build.bat`。

#### 3) 分发方式

把整个 `dist\录屏助手\` 文件夹 **打成 zip** 发给别人即可（不要只发 exe）。

#### 重要说明（务必读）

- **ffmpeg 不会被打进包里**：目标机器仍需要单独安装 ffmpeg，并确保命令行可运行 `ffmpeg`。
- **杀软误报**：PyInstaller 产物偶发误报是常见现象；文件夹分发通常比单文件 exe 更稳，但仍可能需要“添加信任/放行”。

