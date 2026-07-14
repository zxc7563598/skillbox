# create-readme-zh

为项目自动生成专业的中文 README.md 文档的 Claude Code 技能。

## 特性

- **遵循一流中文开源规范** —— 以 Ant Design、TDesign 等项目的 README 为写作参照，结构清晰、语言专业
- **自动识别项目类型** —— 根据项目是开源库、CLI 工具还是 Web 应用，调整 README 的内容侧重
- **按需生成章节** —— 必备的项目简介、快速开始、使用说明，加上推荐有的特性列表、目录结构等，不堆砌模板
- **中文写作规范内建** —— 避免翻译腔、技术术语保留英文、主动语态、GFM 警告语法等

## 安装

```bash
npx skills add zxc7563598/skillbox@create-readme-zh
```

## 使用

在 Claude Code 中输入类似以下指令即可触发技能：

- 「帮我写个 README」
- 「生成 README 文档」
- 「给项目加个说明文档」
- 「完善一下项目介绍」

技能会自动浏览项目文件、理解核心功能，然后按中文开源项目的写作规范生成 `README.md`。

### 生成流程

1. 浏览项目结构和关键文件，理解核心功能和目标用户
2. 学习参考项目（Ant Design、TDesign 等）的 README 结构和语气
3. 确认项目类型和理解是否正确
4. 生成 README 供审阅，支持多轮修改

## 示例

假设你有一个名为 `awesome-cli` 的 Node.js 命令行工具，在项目目录下打开 Claude Code：

```
你：帮我写个 README
Claude Code：我看到这是一个 Node.js CLI 工具，主要功能是批量处理图片...
             确认一下，你想突出哪些功能？
你：重点写批量压缩和水印功能
Claude Code：（生成 README.md，包含安装、常用命令、配置说明等）
```

## 常见问题

### 和直接让 Claude 写 README 有什么区别？

直接用通用提示让 Claude 写 README，生成的内容结构随意、语言风格不稳定。这个技能内建了中文 README 的写作规范和一流项目的参考标准，每次生成质量更一致。

### 支持哪些项目类型？

支持开源库/框架、CLI 工具、Web 应用、脚手架/模板等。技能会根据项目类型自动调整内容侧重。

### 生成的文件会覆盖已有的 README 吗？

技能默认会先检查是否已有 README 文件，如有会询问是否覆盖。你也可以指定输出路径。

## 技术栈

- **运行环境**：Claude Code
- **分发方式**：npx skills（[skills.sh](https://skills.sh)）
- **写作参照**：Ant Design、TDesign React、Element Plus 的 README 规范
