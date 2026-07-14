# Skillbox

个人的 Claude Code Skills 合集。把自己常用的工作流封装成技能，随时取用。

## 为什么会有这个项目

Skills 火了之后，到处都能刷到各种大神分享的技能包。但用过一圈下来发现——别人写的 skill 思路和习惯跟自己总有偏差：触发方式不对、输出格式不是想要的、流程少了一步自己常用的操作。

于是我把常用的几个场景整理成自己的版本，调整到顺手为止。这就是 Skillbox——**它首先是我自己用的工具箱**。

把它公开出来，不是为了推荐你用我的技能。事实上，我做这个项目的初衷恰恰是**不想用别人的 skill**。我希望的是：这个项目能给你一些启发，让你也动手去做自己的技能包。每个人的工作习惯都不一样，最顺手的工具一定是自己打磨出来的。

**每个人都应该有一个自己的技能包。** 这才是 Skills 该有的未来——不是依赖别人的技能，而是把每个人反复做的事情，沉淀成真正匹配自己的工具。

## 安装

虽然我更推荐你自己动手（见下方），但如果你确实想直接用，每个技能可以独立安装：

```bash
npx skills add zxc7563598/skillbox@<技能名称>
```

安装后，在 Claude Code 会话中直接说话或使用 `/` 命令即可触发。具体触发方式和用法见各技能的 README。

## 已有技能

| 技能名称 | 一句话描述 | 安装命令 |
|---------|-----------|---------|
| [analyze-bill](skills/analyze-bill/) | 解析微信/支付宝账单文件，对帐单内容进行多维度分析 | `npx skills add zxc7563598/skillbox@analyze-bill` |
| [create-readme-zh](skills/create-readme-zh/) | 能够分析项目类型和内容，生成符合中文写作规范的专业 README.md 文档 | `npx skills add zxc7563598/skillbox@create-readme-zh` |
| [git-commit](skills/git-commit/) | 理解代码改动意图，生成规范化的 Git 提交信息 | `npx skills add zxc7563598/skillbox@git-commit` |
| [mental-health-companion](skills/mental-health-companion/) | 温暖、非评判的 AI 心理陪伴与情绪疏导 | `npx skills add zxc7563598/skillbox@mental-health-companion` |
| [think-council](skills/think-council/) | 多角度讨论团，分析问题、深入讨论话题、验证想法、发现思维盲区、评估决策风险 | `npx skills add zxc7563598/skillbox@think-council` |

> 后续新增技能会追加到此表格中。

## 目录结构

```
skillbox/
├── skills/
│   ├── analyze-bill/                 # 支付宝/微信账单分析
│   ├── create-readme-zh/             # 中文 README 生成
│   ├── git-commit/                   # Git 提交信息生成
│   ├── mental-health-companion/      # 心理陪伴与情绪疏导
│   └── think-council/                # 多角度讨论团
├── LICENSE
└── README.md
```

## 更推荐：做你自己的技能包

这个项目真正想表达的——**别用我的，做你自己的**。

一个技能本质上就是一个 Markdown 文件（`SKILL.md`）加一些参考文档，门槛很低。你可以：

1. 想想自己有哪些反复做的事情——写提交信息、发周报、查接口文档、生成测试用例……都可以封装成技能
2. 用 `/skill-creator` 或直接手写一个 `SKILL.md`，按你自己的习惯定义触发方式、工作流程和输出格式
3. 放到自己的仓库里，用 `npx skills add <你的仓库>@<技能名>` 安装

如果你想参考这个项目的结构和写法，可以看看 [skills/](skills/) 目录下的各个技能，或者直接 fork 后改成你自己的版本。觉得改得不错也欢迎提 PR 分享回来。
