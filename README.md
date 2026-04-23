## 🎬 cap2jianying（录屏精简版）

> **说明**：本项目仅保留「录制桌面视频 + 可选麦克风录音 + 可选择保存目录 + 圆形悬浮按钮停止录制」功能。

---

### 📋 依赖

| 项 | 要求 |
| --- | --- |
| 系统 | **Windows** |
| FFmpeg | 需在 `PATH` 中能直接运行 `ffmpeg` |
| Python | 自带 `tkinter`（一般 Windows Python 自带） |

#### 安装 Python 依赖（`requirements.txt`）

项目运行依赖在 `requirements.txt` 中（包含录屏与“保存到剪映草稿”所需依赖）。你可以用下面两种方式任选其一。

##### 方式 A：使用 conda（推荐给已有 conda 的用户）

```powershell
conda create -n cap2jy python=3.12 -y
conda activate cap2jy
python -m pip install -U pip
python -m pip install -r .\requirements.txt
```

##### 方式 B：在本项目中创建虚拟环境（原生 venv）

```powershell
python -m venv .\.venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -r .\requirements.txt
```

#### 与剪映技能脚本的目录关系（打包前必读）

根目录下需要存在 **`scripts/`** 与 **`assets/`**（来自 [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) 仓库同名目录，内含 `scripts/jy_wrapper.py`、`scripts/vendor/pyJianYingDraft` 等）。`build.ps1` 会优先使用本仓库内的上述目录；若你把本仓库放在 `jianying-editor-skill` 子目录中，也可自动使用上级目录的 `../scripts` 与 `../assets`。

---

### ▶️ 启动

#### 方式 A：在仓库根目录启动（推荐）

> **注意**：启动命令需要使用“你安装依赖的那个 Python 环境”。  
> - 如果你用的是 conda：先 `conda activate cap2jy` 再运行下面命令。  
> - 如果你用的是 venv：建议用 `.\.venv\Scripts\python`（或先激活 venv）再运行。

```powershell
python .\recorder.py
```

#### 方式 B：一键脚本（推荐）

```powershell
.\run.ps1
```

或双击 `run.bat`。

> 如果你使用 venv 且不想全局污染，推荐直接用 venv 的 python 启动：
>
> ```powershell
> .\.venv\Scripts\python .\recorder.py
> ```

> **提示**：若第一次运行 `run.ps1` 被 PowerShell 拦截，可先执行（当前用户范围即可）：
>
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

### 💾 输出文件

会保存到你选择的目录中：

- `recording_YYYYMMDD_HHMMSS.mp4`
- `ffmpeg_log.txt`

配置会保存到同目录下的 `recorder_config.json`（窗口大小位置、保存目录）。

---

### ❓ 常见问题

- **提示找不到 ffmpeg**：把 ffmpeg 加入系统 PATH，或重启终端后再试。
- **麦克风列表为空**：通常是 ffmpeg 无法枚举 dshow 设备；请确认 ffmpeg 版本支持 dshow，并检查系统隐私设置是否允许应用访问麦克风。

#### 双击 `run.bat` 后找不到 ffmpeg / 麦克风为空

从资源管理器双击启动时，有些机器会出现 PATH 与终端不同，导致程序找不到 `ffmpeg`。

现在程序支持在界面里直接选择 `ffmpeg.exe`：

- 点击设置卡片里的 **「FFmpeg → 选择…」**
- 选择你的 `ffmpeg.exe`（例如 `D:\\AiSoft\\ffmpeg\\bin\\ffmpeg.exe`）
- 再点 **「刷新麦克风」** 即可恢复列表

选择会保存到 `recorder_config.json`，下次双击也能正常识别。

---

### 📦 打包分发（你选择：文件夹分发 / onedir）

本项目提供 `build.ps1`（推荐）与 `build.bat`，使用 **PyInstaller** 生成带时间戳的输出目录，例如：

- `dist_out_YYYYMMDD_HHMMSS/VideoRecorderOnly/`（内含 `VideoRecorderOnly.exe` 与依赖文件）

#### 1) 安装打包依赖

```powershell
python -m pip install -r .\requirements-dev.txt
```

#### 2) 执行打包

```powershell
.\build.ps1
```

或双击 `build.bat`。

#### 3) 分发方式

把整个 `dist_out_...\VideoRecorderOnly\` 文件夹 **打成 zip** 发给别人即可（不要只发 exe）。

#### ⚠️ 重要说明（务必读）

- **ffmpeg 不会被打进包里**：目标机器仍需要单独安装 ffmpeg，并确保命令行可运行 `ffmpeg`。
- **杀软误报**：PyInstaller 产物偶发误报是常见现象；文件夹分发通常比单文件 exe 更稳，但仍可能需要「添加信任/放行」。

---

### 🙏 特别感谢

- 本项目的录制视频能力参考了 [luoluoluo22/jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) 中的「录制视频」技能实现，感谢作者的开源分享。