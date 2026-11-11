# LabDream Version 2.0

吸入制剂撞击器（APSD）数据分析软件。根据原软件的功能、界面流程、使用说明书、
验证文档与验证数据重新实现（独立编写，未使用原软件代码、名称或图片）。

## 2.0 版新增内容

| 内容 | 说明 |
|---|---|
| ECD 随流速自动换算 | 在“用户设置”屏输入校准流速（如 15 / 30 / 60 L/min），各级截止粒径 ECD 立即按说明书第 11.1 章公式重新计算；采样流速相同的运行一并更新 |
| NGI 低流速 | 15–30 L/min 以 15 L/min 为基准（各级指数 0.2692 … 0.8598），30–100 L/min 以 60 L/min 为基准（指数 0.54 … 0.67） |
| 多语言 | English / 简体中文 / Español / Français，登录界面或“工具 → 语言”切换；界面、图表和打印报告均已翻译 |
| 用户管理 | 登录、三种角色（管理员 / 分析员 / 审核员）、密码策略（≥ 8 位，含字母和数字）、首次登录强制改密、连续 5 次失败自动锁定、管理员解锁 / 重置密码、用户只能停用不能删除 |
| 审计追踪 | 记录登录、注销、失败登录、用户变更、新建 / 打开 / 保存 / 关闭文件、流速变更、打印、导出、设置变更等；保存已有文件时须填写修改原因，并记录每个改动值（旧值 → 新值）；记录只能追加，SHA-256 哈希链可校验是否被篡改；可筛选、导出 CSV |
| 数据文件记录 | `.ldd` 文件保存创建人 / 创建时间 / 修改人 / 修改时间 / 版本号；报告页脚显示打印人 |

### 角色权限

| 功能 | 管理员 | 分析员 | 审核员 |
|---|:-:|:-:|:-:|
| 打开、查看数据 | ✓ | ✓ | ✓ |
| 输入 / 修改 / 保存数据、修改流速 | ✓ | ✓ | |
| 修改级名称、手动修改 ECD（维护模式） | ✓ | | |
| 打印、导出 | ✓ | ✓ | ✓ |
| 模板设置 | ✓ | | |
| 用户管理 | ✓ | | |
| 查看审计追踪 | ✓ | | ✓ |

首次启动时会要求创建第一个管理员账户。用户数据库和审计追踪保存在：
Windows `C:\ProgramData\LabDream\labdream.db`，macOS `~/Library/Application Support/LabDream/labdream.db`
（可用环境变量 `LABDREAM_DATA_DIR` 指定其他位置，例如网络共享目录）。

## 功能

| 功能 | 说明 |
|---|---|
| 设备 | 级联撞击器 CI（ACI）、多级液体撞击器 MSLI、Marple-Miller 撞击器 MMI、新一代撞击器 NGI |
| 三步向导 | Screen 1 用户设置（级名称、校准流速、ECD、样品信息）→ Screen 2 沉积数据（最多 12 次运行）→ Screen 3 结果汇总 |
| 计算 | 累积百分比（筛下）、对数-概率单位插值求 MMAD、FPD/FPF（按粒径或按级）、GSD、概率单位 4–6 回归 R²/斜率/截距 |
| 规则 | LOD（累积 <2% 或 >1% 的级少于 3 个）、NA（>50% 在滤膜/顶级或数据不足）、R² 低于设定值则 GSD = NA |
| 分组 | 5 个分组，按粒径范围或按级范围，给出 Particle Dose / Particle Fraction |
| 递送剂量均一性 | 75–125%、80–120%、85–115% 判定 |
| 报告 | EP 方法、USP 方法、图形汇总（每页 3 个运行）、表格汇总、分组结果；打印预览 / 保存 PDF |
| 导出 | CSV（与原软件导出格式相同的结构） |
| 文件 | 原生 `.ldd`（JSON）；可直接打开原软件的 `.CPL` 数据文件 |

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## 打包

- Windows：双击 `build_windows.bat`（需要 Windows 电脑），或上传到 GitHub 后由 GitHub Actions 自动生成
  `LabDream_Setup_2.0.exe` 安装包和 `LabDream_2.0_portable.zip` 免安装版。
- macOS：`./build_macos.sh`，生成 `dist/LabDream.app`。

## 验证

```bash
python3 tests/selftest.py --ui      # 引擎、ECD 换算、用户与审计、四种语言界面与报告
python3 tests/validate_against_reference.py "../Copley原装软件/CITDAS V3.10 Validation/Validation Document - Tables"
```

ECD 换算结果与原软件验证文档附录 A–D（CI、NGI 15/29/30/60/90、MSLI、MMI）逐值一致。

## 目录结构

```
main.py                    程序入口（登录 → 主菜单）
labdream/devices.py        设备定义、ECD 与流速换算
labdream/model.py          数据模型、修改比对
labdream/engine.py         计算引擎（MMAD/GSD/FPD/FPF/R²/分组/LOD/NA）
labdream/security.py       用户、密码、角色权限、审计追踪（SQLite，哈希链）
labdream/session.py        当前登录用户
labdream/i18n.py           语言切换
labdream/translations.py   中文 / 西班牙语 / 法语翻译表
labdream/cpl.py            原 .CPL 数据文件导入
labdream/fileio.py         .ldd 保存/读取、CSV 导出
labdream/charts.py         概率图、沉积柱状图、累积分布图
labdream/reports.py        EP/USP/图形/表格/分组 报告
labdream/ui/               界面（登录、主菜单、三步向导、用户管理、审计追踪、对话框）
tests/                     自测、界面测试、与原软件验证数据的对比
```
