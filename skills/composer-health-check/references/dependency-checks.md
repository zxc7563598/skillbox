# 依赖检查参考手册

各项依赖健康检查的详细指南。

## 安全审计（`composer audit`）

### 理解严重级别

Composer audit 从 PHP 安全数据库（FriendsOfPHP、GitHub Advisory Database）获取公告。每条公告格式：

```
Package: vendor/package
CVE: CVE-2024-xxxxx / GHSA-xxxx-yyyy-zzzz
Title: Remote code execution via deserialization
Link: https://github.com/advisories/GHSA-xxxx-yyyy-zzzz
Affected versions: >=1.0.0,<1.2.3
```

### 严重级别

| 级别 | 判定标准 | 动作 |
|------|----------|------|
| **Critical** | 远程代码执行、认证绕过、SQL 注入、任意文件访问 | 立即修复 |
| **High** | 信息泄露、权限提升、反序列化攻击 | 当前会话修复 |
| **Medium** | DoS、不影响敏感操作的 CSRF、有限数据泄露 | 下次维护窗口修复 |
| **Low** | 理论攻击、需要极端配置才能利用 | 排入常规升级计划 |

### 关注重点

- **直接依赖 vs 间接依赖**：直接依赖的 CVE 优先级高于间接依赖（间接依赖可能你的代码根本不会触发受影响路径）
- **可利用性**：一个你永远不会调用的 CLI 命令中的 CVE，优先级低于请求路由中的 CVE
- **修复方案可用性**：确认是否有已修复的版本。如果没有，公告通常会说明临时方案
- **已废弃包**：没人维护 = 不会有安全补丁。即使当前没有 CVE 也要标记出来

### JSON 输出解析

使用 `composer audit --format=json` 时，关键字段：
- `advisories`：按包名索引的对象，每个值是一个公告数组
- 每条公告：`title`、`cve`、`link`、`affectedVersions`、`reportedAt`
- `abandoned`：被废弃的包列表（需要加 `--abandoned` 参数）

## 过期依赖（`composer outdated`）

### 颜色含义

```
红色  = 大版本落后（semver 不兼容，可能有 breaking changes）
黄色 = 小版本/补丁版本落后（semver 兼容，通常安全）
!    = 不遵循 semver（版本号不能表示兼容性）
```

### JSON 输出结构

```json
{
  "vendor/package": {
    "name": "vendor/package",
    "version": "1.0.0",
    "latest": "3.5.0",
    "latest-status": "semver-safe-update",
    "description": "...",
    "warning": "Abandoned. Use vendor/other instead."
  }
}
```

### 分析规则

1. **落后 ≥2 个大版本**：重点关注——这个包已经发生了重大变化
2. **被标记为 abandoned**：一律报告——没有未来的 bug 修复和安全补丁
3. **直接依赖落后超过一年**：标记为日常维护项
4. **dev-only 依赖落后**：优先级较低，但如果特别旧也值得一提
5. **PHP 本身**：如果约束允许升级到更高版本，标记为改进机会

## 版本约束质量

### composer.json 中要检查的问题

**太松（需要收紧）：**
```json
"require": {
    "php": ">=7.4",           // 没有上界——PHP 9 出来直接炸
    "guzzlehttp/guzzle": "*", // 任意版本——行为不可预测
    "monolog/monolog": ">=1.0" // 没有上界——可能装到 v99
}
```

**太紧（需要放宽）：**
```json
"require": {
    "php": "8.1.0",            // 精确锁定——minor/patch 更新全被阻塞
    "symfony/console": "6.3.*" // 通配符——可能拉到不想要的 minor 变化
}
```

**好的写法：**
```json
"require": {
    "php": "^8.1",              // 允许 8.1.x, 8.2.x 等（适合库）
    "symfony/console": "^6.3",  // 允许 6.3-6.x（适合应用）
    "guzzlehttp/guzzle": "^7.0" // 宽但有上界（适合库）
}
```

### 库 vs 应用

| 关注点 | 库 | 应用 |
|--------|-----|------|
| PHP 版本约束 | 保持宽松：`^8.1` | 可以具体：`^8.3` |
| 依赖版本约束 | 保持宽松：`^2.0` | 可以具体：`^2.5` |
| `composer bump`（不限制） | ❌ 不要用 | ✅ 随便用 |
| `composer bump --dev-only` | ✅ 可以用 | ✅ 可以用 |

## PHP 版本阻塞排查

### 使用 `composer why-not php <版本>`

```bash
composer why-not php 8.3
```

输出会展示依赖链：
```
vendor/package  1.0.0  requires php (^8.1)
└── vendor/other  2.0.0  requires php (^8.2)
```

从下往上看——最深的依赖才是真正阻止升级的包。

### 针对性建议

- 如果只有 dev 依赖阻塞：优先级低，方便的时候处理
- 如果是直接依赖阻塞：检查该依赖是否有允许更高 PHP 版本的新版本
- 如果是间接依赖阻塞：检查升级其父依赖是否能解决
- 没有阻塞项 = PHP 升级畅通无阻——如果项目版本低于 8.1，建议升级

## 快速依赖扫描

30 秒快速检查：

```bash
composer audit --format=json --no-interaction --no-ansi
composer outdated --direct --format=json --no-interaction --no-ansi
```

只看：
1. 严重程度 ≥ high 的 CVE
2. 落后 ≥2 个大版本的直接依赖
3. 已废弃的包
