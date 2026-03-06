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
