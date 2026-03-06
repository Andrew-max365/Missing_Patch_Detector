# Missing Patch Detector 🛡️

**Missing Patch Detector** 是一个用于自动扫描 Git 代码仓库及其所有活跃分支，检测特定安全补丁（CVE Fix）是否已被应用的自动化安全分析工具。

该工具专为漏洞分析师和软件供应链安全工程师设计，完美解决**上游开源项目发布安全补丁后，下游项目（或同一个项目的多个历史长周期分支）漏打补丁**的痛点，极大提升补丁移植（Patch Backporting）的工作效率。

## ✨ 核心特性

- 📥 **自动补丁采集**: 给定一个 GitHub/GitLab Commit URL，自动下载并精准解析对应的 unified diff 数据。
- 🔍 **智能仓库扫描**: 自动过滤掉长期未活跃的僵尸分支（基于时间戳），自动在不同分支间切换，并拥有**文件路径回溯定位能力**（自动解决历史分支中文件被重命名或移动导致找不到文件的问题）。
- ⚖️ **高容错代码比对**: 基于特征行匹配比例（Confidence Score）进行检测，避免由于空格、换行等细微差别导致的误报。
- 🤖 **LLM-Ready 架构**: 预留了高度解耦的大模型（LLM）调用回调接口，为应对代码重构导致文本匹配失效时的“语义级漏洞检测”打下基础。

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

使用 `MissingPatchPipeline` 可以通过几行代码实现从下载补丁到输出报告的完整流水线。

```python
from missing_patch_detector import MissingPatchPipeline

# 初始化 Pipeline
pipeline = MissingPatchPipeline()

# 运行扫描
report = pipeline.run(
    commit_url="[https://github.com/torvalds/linux/commit/8c1f34d](https://github.com/torvalds/linux/commit/8c1f34d)", # 上游修复 Commit
    repo_url="[https://github.com/example/linux-fork](https://github.com/example/linux-fork)",              # 目标下游仓库
    local_path="/tmp/linux-fork",                                  # 本地克隆路径
    max_age_days=365,                                              # 仅扫描最近一年内有提交的活跃分支
    include_local_branches=True
)

print(f"✅ 已打补丁的分支: {report.patched_branches}")
print(f"❌ 遗漏补丁的分支: {report.missing_branches}")

# 查看置信度等详细信息
for res in report.branch_results:
    print(f"分支: {res.branch} | 匹配度: {res.confidence:.2f} | 丢失文件: {res.missing_files}")
```

## 🏗️ 架构设计

本项目采用高内聚、低耦合的模块化设计：

- **`PatchCollector`**: 负责网络请求、`.patch` 文件下载及 diff 解析。提供 `generate_llm_signature` 用于生成语义特征。
- **`RepoScanner`**: 包装了 `GitPython`，负责本地代码库的管理、分支的筛选以及文件源码的安全读取（包含 Best-effort Fallback 机制）。
- **`PatchPresenceDetector`**: 核心决策引擎。负责计算差异补丁特征在新分支代码中的存活比例。
- **`MissingPatchPipeline`**: 顶层调度器，将上述三大模块组合成自动化流水线，输出 `DetectionReport`。

## 🧪 测试

项目包含完整的单元测试与集成测试，确保核心逻辑不受 Git 环境与网络的干扰。

```bash
pytest
# 或查看详细输出
pytest -v
```

## 🗺️ Roadmap (开发计划)

- [x] **Phase 1: 文本特征检测 (Text/Context Matching)** - 基于增量代码比例计算的静态匹配（当前版本）。
- [ ] **Phase 2: LLM 语义检测 (Semantic Matching Fallback)** - 当代码特征匹配率不足时，自动将补丁特征与源码发送至大模型（如 Gemini / GPT-4）进行语义级判定。
- [ ] **Phase 3: 自动化报告生成** - 内置 Markdown 与 JSON 格式的审计报告导出能力。
- [ ] **Phase 4: AST 语法树特征支持** - 集成 `Tree-sitter`，提供比纯文本匹配更精确的抽象语法树级匹配。

