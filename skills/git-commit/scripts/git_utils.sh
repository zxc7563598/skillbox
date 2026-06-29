#!/bin/bash
# Git 操作辅助函数 — git-commit skill
# 用法：source scripts/git_utils.sh

# 检查是否在 git 仓库中
is_git_repo() {
    git rev-parse --git-dir >/dev/null 2>&1
}

# 获取当前分支名
get_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null
}

# 获取简要状态（porcelain 格式，便于解析）
get_status() {
    git status --porcelain 2>/dev/null
}

# 获取工作区未暂存的改动
get_unstaged_diff() {
    git diff --no-color 2>/dev/null
}

# 获取已暂存的改动
get_staged_diff() {
    git diff --cached --no-color 2>/dev/null
}

# 获取合并后的全部改动（暂存 + 未暂存）
get_all_diff() {
    # 先展示暂存区，再展示工作区
    {
        git diff --cached --no-color 2>/dev/null
        git diff --no-color 2>/dev/null
    } | cat
}

# 获取改动的文件列表（不含未跟踪文件）
get_changed_files() {
    git diff --name-only HEAD 2>/dev/null
}

# 获取改动的统计信息
get_diff_stats() {
    git diff --stat HEAD 2>/dev/null
}

# 暂存所有改动
stage_all() {
    git add -A 2>/dev/null
}

# 暂存指定文件
stage_files() {
    local files=("$@")
    git add -- "${files[@]}" 2>/dev/null
}

# 执行提交（接受 subject 和 body 两个参数）
create_commit() {
    local subject="$1"
    local body="$2"

    if [ -n "$body" ]; then
        git commit -m "$subject" -m "$body" 2>/dev/null
    else
        git commit -m "$subject" 2>/dev/null
    fi
}

# 获取最近一次提交信息
get_last_commit_msg() {
    git log -1 --format="%s" 2>/dev/null
}

# 获取 diff 行数
get_diff_line_count() {
    git diff --no-color 2>/dev/null | wc -l | tr -d ' '
}
