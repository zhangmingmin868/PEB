# LabDream Version 1.0

吸入制剂撞击器（APSD）数据分析软件。根据文件夹中原软件的功能、界面流程、
验证文档与验证数据重新实现（独立编写，未使用原软件代码、名称或图片）。

## 功能

| 功能 | 说明 |
|---|---|
| 设备 | 级联撞击器 CI（ACI）、多级液体撞击器 MSLI、Marple-Miller 撞击器 MMI、新一代撞击器 NGI |
| 三步向导 | Screen 1 用户设置（级名称、校准流速、ECD、样品信息）→ Screen 2 沉积数据（最多 12 次运行）→ Screen 3 结果汇总 |
| 计算 | 累积百分比（筛下）、对数-概率单位插值求 MMAD、FPD/FPF（按粒径或按级）、GSD、概率单位 4–6 回归 R²/斜率/截距 |
| 规则 | LOD（累积 <2% 或 >1% 的级少于 3 个）、NA（>50% 在滤膜/顶级或数据不足）、R² 低于设定值则 GSD = NA |
| 分组 | 5 个分组，按粒径范围或按级范围，给出 Particle Dose / Particle Fraction |
| 递送剂量均一性 | 75–125%、80–120%、85–115% 判定 |
| ECD 换算 | CI/MSLI/MMI：d·√(Qcal/Q)；NGI：Ph. Eur. 2.9.18 指数公式 |
| 其他选项 | mg/µg 单位、预分离器显示/隐藏、CI 高流速去除 Stage 6/7、喷重（Shot Weight）报告 |
| 报告 | EP 方法、USP 方法、图形汇总（每页 3 个运行）、表格汇总、分组结果；打印预览 / 保存 PDF |
| 导出 | CSV（与原软件导出格式相同的结构） |
| 文件 | 原生 `.ldd`（JSON）；可直接打开原软件的 `.CPL` 数据文件 |
| 设置 | 每种设备可设定模板文件（“Read from Template”）和默认数据目录 |

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Windows：

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## 打包为可执行程序

PyInstaller 只能打包当前所在系统的程序：Windows 版必须在 Windows 电脑上打包，macOS 版在 Mac 上打包。

### Windows（生成 LabDream.exe）

1. 安装 64 位 Python 3.9 或更高版本（https://www.python.org），安装时勾选 **Add python.exe to PATH**。
2. 把整个 `LabDream` 文件夹复制到 Windows 电脑上。
3. 双击 `build_windows.bat`（第一次需要联网下载 PySide6 和 PyInstaller，约 150 MB）。
4. 生成的程序在 `dist\LabDream\LabDream.exe`。分发时复制**整个** `dist\LabDream` 文件夹，目标电脑不需要安装 Python。

### macOS（生成 LabDream.app）

```bash
./build_macos.sh
```

生成 `dist/LabDream.app`（约 67 MB）。

### 相关文件

| 文件 | 作用 |
|---|---|
| `build_windows.bat` | Windows 一键打包 |
| `build_macos.sh` | macOS 一键打包 |
| `labdream.spec` | PyInstaller 配置（图标、版本信息、需打包的模块） |
| `version_info.txt` | Windows exe 属性中显示的版本信息（LabDream Version 1.0） |
| `assets/` | 程序图标（.ico / .icns / .png），由 `tools/make_icons.py` 生成 |

## 验证

`tests/validate_against_reference.py` 读取原软件验证包中的 `.CPL` 输入文件，
用 LabDream 计算后与原软件导出的 `.CSV` 结果逐值比较：

```bash
python3 tests/validate_against_reference.py "../Copley原装软件/CITDAS V3.10 Validation/Validation Document - Tables"
```

## 目录结构

```
main.py                    程序入口
labdream/devices.py        设备定义、ECD 与流速换算
labdream/model.py          数据模型
labdream/engine.py         计算引擎（MMAD/GSD/FPD/FPF/R²/分组/LOD/NA）
labdream/cpl.py            原 .CPL 数据文件导入
labdream/fileio.py         .ldd 保存/读取、CSV 导出
labdream/charts.py         概率图、沉积柱状图、累积分布图（屏幕与打印共用）
labdream/reports.py        EP/USP/图形/表格/分组 报告
labdream/ui/               界面（主菜单、三步向导、对话框）
tests/                     与原软件验证数据的对比测试、界面自动测试
tools/make_icons.py        生成程序图标
build_windows.bat          Windows 打包脚本
build_macos.sh             macOS 打包脚本
labdream.spec              PyInstaller 配置
```
