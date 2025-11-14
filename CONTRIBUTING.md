# 感谢你参与贡献！

我们非常欢迎社区的贡献。在提交你的贡献之前，请花点时间阅读以下指南。

## 目录

- [如何贡献](#如何贡献)
  - [报告 Bug](#报告-bug)
  - [提出功能建议](#提出功能建议)
  - [提交你的贡献 (Pull Request)](#提交你的贡献-pull-request)
- [本地开发设置](#本地开发设置)
- [代码风格指南](#代码风格指南)
  - [Commit 消息规范](#commit-消息规范)

---

## 如何贡献

### 报告 Bug

如果你在使用的过程中发现了 Bug，请通过创建 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues) 来报告它。

为了让我们能更快地定位问题，请在 Issue 中尽量包含以下信息：

- **清晰的标题**：简明扼要地描述问题。
- **复现步骤**：详细说明如何一步步地复现这个 Bug。
- **期望的行为**：你认为在上述步骤后应该发生什么。
- **实际发生的行为**：实际发生了什么，包括错误信息、截图等。
- **你的环境**：操作系统、软件版本等。

### 提出功能建议

我们随时欢迎新的功能建议！请通过创建 [Issue](https://github.com/TouhouGleaners/danmaku-sender/issues) 来告诉我们你的想法。

请在建议中详细描述：

- **解决了什么问题**：这个功能主要用于解决用户的什么痛点。
- **你建议的实现方式**：尽可能详细地描述这个功能应该如何工作。

### 提交你的贡献 (Pull Request)

我们通过 Pull Request (PR) 来接受代码贡献。提交流程如下：

1.  **Fork 本仓库** 到你自己的 GitHub 账户。
2.  将你 Fork 的仓库 **Clone** 到你的本地。
3.  从 `main` 分支创建一个新的 **Feature 分支**，例如 `git checkout -b feature/a-cool-new-feature`。
4.  在新的分支上进行修改和开发。
5.  **Commit** 你的修改。请确保你的 Commit 消息遵循我们的规范（见下文）。
6.  将你的 Feature 分支 **Push** 到你 Fork 的仓库。
7.  在 GitHub 上创建一个 **Pull Request**，目标分支为本仓库的 `main` 分支。

## 本地开发设置

1.  Clone 你 Fork 的仓库到本地：
    ```bash
    git clone https://github.com/TouhouGleaners/danmaku-sender.git
    cd danmaku-sender
    ```

2.  安装项目依赖：
    ```bash
    pip install -r requirements.txt
    ```

## 代码风格指南

我们遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008/) 代码风格。在提交代码前，请使用 `black` 或 `flake8` 等工具进行检查和格式化。  
(但就目前来讲，代码风格的检查是*不必要的*。)

### Commit 消息规范

我们遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范。这能让我们的提交历史更加清晰，并有助于自动化生成版本日志。  
提交语言可根据个人习惯选择。

Commit 消息格式为：`<type>: <description>`

-   **feat**: 新增功能
-   **fix**: 修复 Bug
-   **docs**: 仅修改文档
-   **style**: 代码格式修改（不影响代码逻辑）
-   **refactor**: 代码重构
-   **test**: 新增或修改测试
-   **chore**: 构建流程、辅助工具的变动

**示例:**
* `feat: Add user authentication feature`
* `fix: Correct a typo in the documentation`
* `fix: 修正文档中的拼写错误`

---

再次感谢你的贡献！