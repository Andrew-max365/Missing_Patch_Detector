# Missing Patch Detector 🛡️

**Missing Patch Detector** 是一个用于自动扫描 Git 代码仓库及其所有活跃分支，检测特定安全补丁（CVE Fix）是否已被应用的自动化安全分析工具。

该工具专为漏洞分析师和软件供应链安全工程师设计，解决上游开源项目发布安全补丁后，下游项目（或同一个项目的多个历史长周期分支）漏打补丁的痛点，极大提升补丁移植（Patch Backporting）的工作效率。

## ✨ 核心特性

- 🔗 **CVE 自动解析**: 只需输入 CVE ID，工具即可通过 OSV API 自动解析并获取对应的上游修复 Commit URL。
- 📥 **自动补丁采集**: 给定 Commit URL 后，自动下载并精准解析对应的 unified diff 数据。
- 🔍 **智能仓库扫描**: 自动过滤非活跃分支，并具备**文件路径回溯定位能力**（自动解决由于文件重命名或移动导致的检测失败问题）。
- ⚖️ **高容错检测引擎**: 
    - **文本比对**: 基于特征行匹配比例（Confidence Score）进行检测，规避空格和换行差异的影响。
    - **LLM 语义判定**: 预留并初步实现了大模型（LLM）调用接口。当代码重构导致文本匹配率过低时，可自动请求 LLM 进行语义级漏洞检测判定。
- 📊 **多格式报告输出**: 内置 Markdown 和 JSON 格式的审计报告导出能力，方便人工阅读或自动化系统集成。

## 📦 安装

确保你的环境为 Python 3.10+，并在环境中安装了 Git。

```bash
# 克隆仓库
git clone [https://github.com/andrew-max365/missing_patch_detector.git](https://github.com/andrew-max365/missing_patch_detector.git)
cd missing_patch_detector

# 本地安装
pip install .

# 或者安装开发依赖以运行测试
pip install ".[test]"
```

## 🚀 快速开始

### 场景一：基于 CVE ID 自动运行完整流水线
这是最自动化的方式，系统会自动解析 CVE 修复地址并扫描目标仓库。

```python
from missing_patch_detector import MissingPatchPipeline

# 初始化 Pipeline
pipeline = MissingPatchPipeline()

# 运行扫描：自动根据 CVE 解析补丁并检查目标仓库分支
reports = pipeline.run_for_cve(
    cve_id="CVE-2021-44228",
    repo_url="[https://github.com/example/log4j-fork](https://github.com/example/log4j-fork)",
    local_path="/tmp/log4j-fork"
)

for report in reports:
    print(report.to_markdown())
```

### 场景二：指定修复 Commit URL 进行扫描
```python
from missing_patch_detector import MissingPatchPipeline

pipeline = MissingPatchPipeline()
report = pipeline.run(
    commit_url="[https://github.com/torvalds/linux/commit/8c1f34d](https://github.com/torvalds/linux/commit/8c1f34d)", # 上游修复 Commit
    repo_url="[https://github.com/example/linux-fork](https://github.com/example/linux-fork)",              # 目标下游仓库
    local_path="/tmp/linux-fork",                                  # 本地路径
    max_age_days=365                                               # 仅扫描最近一年活跃分支
)

print(f"✅ 已打补丁的分支: {report.patched_branches}")
print(f"❌ 遗漏补丁的分支: {report.missing_branches}")
```

## 🏗️ 架构设计

本项目采用高内聚、低耦合的模块化设计：

- **`CVEResolver`**: 负责将 CVE ID 通过 OSV API 映射为具体的 Git 修复提交信息。
- **`PatchCollector`**: 负责补丁下载、diff 解析以及生成用于 LLM 判定的语义特征。
- **`RepoScanner`**: 封装 `GitPython`，负责本地仓库管理、分支筛选及源代码检索（含 Fallback 回溯逻辑）。
- **`PatchPresenceDetector`**: 核心决策引擎。负责计算补丁特征在目标代码中的存活比例，并支持 LLM 辅助决策。
- **`MissingPatchPipeline`**: 顶层调度器，将上述模块组合成端到端的自动化扫描流水线。

## 🧪 测试

项目包含针对 CVE 解析、补丁采集、扫描逻辑及流水线的完整测试：

```bash
pytest
# 或查看详细输出
pytest -v
```
