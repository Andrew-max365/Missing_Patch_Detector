# Missing Patch Detector 🛡️

**Missing Patch Detector** 是一个用于自动扫描 Git 代码仓库及其所有活跃分支，检测特定安全补丁（CVE Fix）是否已被应用的自动化安全分析工具。

该工具专为漏洞分析师和软件供应链安全工程师设计，完美解决上游开源项目发布安全补丁后，下游项目（或同一个项目的多个历史长周期分支）漏打补丁的痛点，极大提升补丁移植（Patch Backporting）的排查效率。

## ✨ 核心特性 (v1.0.0 生产可用版)

- ⚡ **极速内存并发扫描**: 彻底摒弃缓慢的磁盘 `checkout`。基于并发线程池与 Git 底层对象（Tree/Blob）的纯内存读取，在扫描包含成百上千个分支的巨型仓库（如 Linux Kernel）时，速度成百倍提升。
- 🔗 **CVE 自动解析**: 只需输入 CVE ID，工具即可通过 OSV API 自动定位并获取上游修复的 Git Commit URL。
- 🔍 **智能回溯与 OOM 防御**: 具备**文件路径回溯定位能力**，自动解决历史分支中文件被重命名导致的漏报。同时内置大文件防御机制（默认跳过 >5MB 的单文件），彻底杜绝内存溢出。
- ⚖️ **双模高容错检测引擎**: 
    - **静态特征比对**: 基于补丁增量行的 Confidence Score 计算，规避空格和换行差异。
    - **智能语义判定 (LLM Fallback)**: 当代码被重构导致静态匹配失败时，自动提取补丁发生处的**滑动上下文窗口 (Sliding Window)** 交给大模型进行语义纠错。内置并发限流（Semaphore）与指数退避重试（Exponential Backoff）机制，从容应对 API Rate Limit。
- 🐳 **安全合规的容器化**: 提供开箱即用的 Docker 镜像。默认以非特权用户运行，并完美处理了数据持久化卷（Volume）的权限隔离。

## 📦 安装与部署

### 方式一：Docker 容器部署（推荐）
系统提供精简安全的容器化方案，将工具与环境完全隔离，非常适合在轻量级服务器或 CI/CD 流水线中作为定时任务运行。

```bash
# 1. 克隆仓库
git clone [https://github.com/andrew-max365/missing_patch_detector.git](https://github.com/andrew-max365/missing_patch_detector.git)
cd missing_patch_detector

# 2. 构建镜像
docker build -t missing-patch-detector .

# 3. 运行挂载 (映射本地的数据与报告目录)
docker run --rm \
  -v $(pwd)/data/repos:/data/repos \
  -v $(pwd)/data/reports:/data/reports \
  missing-patch-detector python -c "from missing_patch_detector import MissingPatchPipeline; ..."
