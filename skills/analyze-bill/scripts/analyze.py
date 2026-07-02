"""账单数据分析模块。

提供对标准化账单数据的多维度统计分析，包括按时间、商户、交易类型、
支付来源等维度的收入/支出汇总，支持自定义日期区间过滤和目标商户归一化。

用法示例::

    import json
    from analyze import BillAnalyzer

    with open("bills.json", "r", encoding="utf-8") as f:
        bills = json.load(f)

    analyzer = BillAnalyzer(bills)

    # 总览
    summary = analyzer.get_summary()

    # 每月支出
    monthly = analyzer.get_summary(group_by="month", direction="expense")

    # 指定商户分析
    meituan = analyzer.get_by_target("美团", group_by="month")

    # 按类型分析
    food = analyzer.get_by_type("餐饮美食", group_by="month")
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional, Union

# ---------------------------------------------------------------------------
# 运行时可配置的状态集 — 由 load_config() 或 auto_detect_config() 填充。
# 不再硬编码任何业务规则。
# ---------------------------------------------------------------------------
_SUCCESS_STATUSES: set[str] = set()
_INCOME_LABELS: set[str] = set()
_EXPENSE_LABELS: set[str] = set()
_NEUTRAL_LABELS: set[str] = set()

# 商户别名 — {归一化名: [匹配模式列表]}
_TARGET_ALIASES: dict[str, list[Union[str, re.Pattern]]] = {}

# 归一化缓存与构建标记
_normalized_cache: dict[str, str] = {}
_aliases_built: bool = False


def load_config(config: dict[str, Any]) -> None:
    """从配置字典加载分析参数，替换模块级默认值。

    配置格式与 discover.py 输出一致。调用后重置所有缓存。

    Args:
        config: 包含 status_mapping / direction_mapping / target_aliases 的字典。
    """
    global _SUCCESS_STATUSES, _INCOME_LABELS, _EXPENSE_LABELS, _NEUTRAL_LABELS
    global _TARGET_ALIASES, _aliases_built, _normalized_cache

    _SUCCESS_STATUSES = {
        s for s, cat in config.get("status_mapping", {}).items()
        if cat == "success"
    }

    dir_map = config.get("direction_mapping", {})
    _INCOME_LABELS = {d for d, cat in dir_map.items() if cat == "income"}
    _EXPENSE_LABELS = {d for d, cat in dir_map.items() if cat == "expense"}
    _NEUTRAL_LABELS = {d for d, cat in dir_map.items() if cat == "neutral"}

    raw_aliases = config.get("target_aliases", {})
    _TARGET_ALIASES.clear()
    for canonical, patterns in raw_aliases.items():
        compiled: list[Union[str, re.Pattern]] = []
        for pat in patterns:
            if any(c in pat for c in ".^$*+?{}[]\\|()"):
                compiled.append(re.compile(pat))
            else:
                compiled.append(pat)
        _TARGET_ALIASES[canonical] = compiled

    _normalized_cache.clear()
    _aliases_built = False


def auto_detect_config(bills: list[dict]) -> dict[str, Any]:
    """从账单数据中自动检测配置。

    使用与 discover.py 完全相同的启发式规则，确保无配置文件时也能正常工作。

    Args:
        bills: 原始账单列表。

    Returns:
        与 discover.py 输出格式一致的配置字典。
    """
    status_counter: dict[str, int] = defaultdict(int)
    direction_counter: dict[str, int] = defaultdict(int)
    for b in bills:
        status_counter[b["status"]] += 1
        direction_counter[b["income_expense"]] += 1

    def _cat_status(s: str) -> str:
        if any(kw in s for kw in ["成功", "已", "完成", "存入", "转入", "解冻", "退还"]):
            return "success"
        if any(kw in s for kw in ["失败", "关闭"]):
            return "failure"
        return "unknown"

    def _cat_direction(d: str) -> str:
        if "收入" in d:
            return "income"
        if "支出" in d:
            return "expense"
        return "neutral"

    return {
        "status_mapping": {s: _cat_status(s) for s in status_counter},
        "direction_mapping": {d: _cat_direction(d) for d in direction_counter},
        "target_aliases": {},
    }

# 反向索引：在首次使用时构建
_normalized_cache: dict[str, str] = {}
_aliases_built: bool = False


def _build_alias_lookup() -> None:
    """将 _TARGET_ALIASES 展开为 {原始名: 归一化名} 的快速查找表。"""
    global _aliases_built, _normalized_cache
    if _aliases_built:
        return
    _normalized_cache.clear()
    for normalized, patterns in _TARGET_ALIASES.items():
        for pat in patterns:
            if isinstance(pat, str):
                _normalized_cache[pat] = normalized
            else:
                # regex 模式先在构建时缓存 exact flag，实际匹配在 normalize_target 中处理
                pass
    _aliases_built = True


def normalize_target(raw: str) -> str:
    """将原始商户名归一化为标准名称。

    先查精确匹配表，再尝试正则匹配。未命中则返回原始名称。

    Args:
        raw: 原始商户名称。

    Returns:
        归一化后的商户名称。
    """
    _build_alias_lookup()
    if raw in _normalized_cache:
        return _normalized_cache[raw]
    for normalized, patterns in _TARGET_ALIASES.items():
        for pat in patterns:
            if isinstance(pat, re.Pattern):
                if pat.fullmatch(raw):
                    _normalized_cache[raw] = normalized
                    return normalized
    _normalized_cache[raw] = raw
    return raw


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _is_success(status: str) -> bool:
    """判断一条账单是否为成功交易。

    Args:
        status: 账单的 status 字段值。

    Returns:
        True 表示成功交易。
    """
    return status in _SUCCESS_STATUSES


def _get_direction(income_expense: str) -> Optional[Literal["income", "expense"]]:
    """将 income_expense 字符串映射为方向。

    Args:
        income_expense: 账单的 income_expense 字段值。

    Returns:
        ``"income"`` 表示收入，``"expense"`` 表示支出，``None`` 表示不计收支。
    """
    if income_expense in _INCOME_LABELS:
        return "income"
    if income_expense in _EXPENSE_LABELS:
        return "expense"
    return None


def _parse_amount(amount: str | float) -> float:
    """将金额字符串转换为浮点数。

    Args:
        amount: 金额，可以是字符串或数字。

    Returns:
        浮点数金额。
    """
    if isinstance(amount, (int, float)):
        return float(amount)
    return float(amount.strip())


def _parse_time(time_str: str) -> datetime:
    """将时间字符串解析为 datetime 对象。

    Args:
        time_str: 格式为 ``%Y-%m-%d %H:%M:%S`` 的时间字符串。

    Returns:
        datetime 对象。
    """
    return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")


def _filter_bills(
    bills: list[dict],
    *,
    only_success: bool = True,
    start: str | date | datetime | None = None,
    end: str | date | datetime | None = None,
    direction: Literal["income", "expense", "all"] = "all",
    targets: str | Iterable[str] | None = None,
    types: str | Iterable[str] | None = None,
    sources: str | Iterable[str] | None = None,
) -> list[dict]:
    """通用的账单过滤方法。

    Args:
        bills: 账单列表。
        only_success: 是否仅保留成功交易。
        start: 起始时间（含），支持 ``"YYYY-MM-DD"`` 字符串、date 或 datetime。
        end: 结束时间（含），格式同 start。
        direction: 收支方向过滤。
        targets: 商户名或商户名列表（支持归一化匹配）。
        types: 交易类型或类型列表。
        sources: 来源或来源列表（如 ``"alipay"`` 或 ``"wechat"``）。

    Returns:
        过滤后的账单列表。
    """
    # 预处理时间边界
    if isinstance(start, str):
        start = datetime.strptime(start, "%Y-%m-%d")
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time())
    if isinstance(end, str):
        end = datetime.strptime(end, "%Y-%m-%d")
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, datetime.max.time())

    # 预处理列表参数
    if isinstance(targets, str):
        targets = {targets}
    elif targets is not None:
        targets = set(targets)
    if isinstance(types, str):
        types = {types}
    elif types is not None:
        types = set(types)
    if isinstance(sources, str):
        sources = {sources}
    elif sources is not None:
        sources = set(sources)

    result = []
    for bill in bills:
        if only_success and not _is_success(bill["status"]):
            continue

        if direction != "all":
            d = _get_direction(bill["income_expense"])
            if d != direction:
                continue

        if start is not None or end is not None:
            t = _parse_time(bill["time"])
            if start is not None and t < start:
                continue
            if end is not None and t > end:
                continue

        if targets is not None:
            normalized = normalize_target(bill["target"])
            if normalized not in targets:
                continue

        if types is not None:
            if bill["type"] not in types:
                continue

        if sources is not None:
            if bill["source"] not in sources:
                continue

        result.append(bill)

    return result


def _sum_amount(bills: list[dict]) -> float:
    """计算账单列表的金额总和。

    Args:
        bills: 账单列表。

    Returns:
        总金额（浮点数）。
    """
    return sum(_parse_amount(b["amount"]) for b in bills)


def _count(bills: list[dict]) -> int:
    """计算账单条数。"""
    return len(bills)


def _month_key(time_str: str) -> str:
    """从时间字符串提取年月键，如 ``"2024-07"``。"""
    return time_str[:7]


def _year_key(time_str: str) -> str:
    """从时间字符串提取年份键，如 ``"2024"``。"""
    return time_str[:4]


# ---------------------------------------------------------------------------
# 统一结果结构
# ---------------------------------------------------------------------------

def _make_result(
    label: str,
    bills: list[dict],
    *,
    direction: str = "all",
) -> dict[str, Any]:
    """构建单条统计结果。

    Args:
        label: 统计维度标签（如月份、类型名、商户名）。
        bills: 属于该维度的账单列表。
        direction: 收支方向过滤标记，仅用于顶层 summary 的 direction 字段。

    Returns:
        包含 count、total_amount、income、expense、avg_per_transaction、
        max_single、min_single 等字段的字典。
    """
    income_bills = [b for b in bills if _get_direction(b["income_expense"]) == "income"]
    expense_bills = [b for b in bills if _get_direction(b["income_expense"]) == "expense"]

    income_amount = _sum_amount(income_bills)
    expense_amount = _sum_amount(expense_bills)
    total_amount = income_amount - expense_amount

    # 找出金额最大和最小的单笔交易
    def _amount(b: dict) -> float:
        return _parse_amount(b["amount"])

    max_bill = max(bills, key=_amount) if bills else None
    min_bill = min(bills, key=_amount) if bills else None

    return {
        "label": label,
        "count": _count(bills),
        "total_amount": round(total_amount, 2),
        "income": {
            "count": _count(income_bills),
            "amount": round(income_amount, 2),
        },
        "expense": {
            "count": _count(expense_bills),
            "amount": round(expense_amount, 2),
        },
        "avg_per_transaction": round(total_amount / _count(bills), 2) if bills else 0,
        "max_single": {
            "amount": round(_amount(max_bill), 2) if max_bill else 0,
            "target": normalize_target(max_bill["target"]) if max_bill else "",
            "time": max_bill["time"] if max_bill else "",
        },
        "min_single": {
            "amount": round(_amount(min_bill), 2) if min_bill else 0,
            "target": normalize_target(min_bill["target"]) if min_bill else "",
            "time": min_bill["time"] if min_bill else "",
        },
    }


# ---------------------------------------------------------------------------
# BillAnalyzer
# ---------------------------------------------------------------------------

class BillAnalyzer:
    """账单分析器。

    封装账单列表并提供多维度统计分析方法。所有统计默认仅计入成功交易。

    Attributes:
        bills: 原始账单列表。
        success_bills: 仅包含成功交易的账单列表（惰性缓存）。
    """

    def __init__(self, bills: list[dict], config: dict[str, Any] | None = None) -> None:
        """初始化分析器。

        根据提供的配置或自动检测结果设置成功状态、收支方向和商户别名。
        配置格式与 discover.py 输出一致。

        Args:
            bills: 账单列表，通常来自 parse.py 导出的 JSON。
            config: 分析配置字典。为 None 时自动从数据中检测。
        """
        self.bills = bills
        self._success_bills: list[dict] | None = None
        if config is not None:
            load_config(config)
        else:
            load_config(auto_detect_config(bills))

    @property
    def success_bills(self) -> list[dict]:
        """成功交易的账单列表（惰性计算并缓存）。"""
        if self._success_bills is None:
            self._success_bills = [
                b for b in self.bills if _is_success(b["status"])
            ]
        return self._success_bills

    # ---- 总览 ----

    def get_summary(
        self,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取账单总览统计。

        按指定时间粒度分组统计成功交易的收入/支出情况。

        Args:
            group_by: 分组粒度。``"year"`` / ``"month"`` / ``"day"`` / ``"none"``（不分组）。
            direction: 收支方向过滤。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            统计结果列表，每项包含 label、count、total_amount、income、expense、
            avg_per_transaction。当 group_by="none" 时返回单元素列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,  # 已经是 success_bills，无需重复过滤
            start=start,
            end=end,
            direction=direction,
        )

        if group_by == "none":
            return [_make_result("总览", bills, direction=direction)]

        key_func: Callable[[str], str]
        if group_by == "month":
            key_func = _month_key
        elif group_by == "day":
            key_func = lambda t: t[:10]
        else:
            key_func = _year_key

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key_func(b["time"])].append(b)

        return [
            _make_result(key, group)
            for key, group in sorted(groups.items())
        ]

    # ---- 按商户 ----

    def get_by_target(
        self,
        target: str,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取指定商户的消费/收入统计。

        商户名会经过归一化处理，例如 ``"上海赫程国际旅行社有限公司"`` 会自动
        归入 ``"携程"``。

        Args:
            target: 目标商户名（归一化后匹配）。
            group_by: 分组粒度。
            direction: 收支方向过滤。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            统计结果列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
            targets=[target],
        )

        if group_by == "none":
            return [_make_result(target, bills, direction=direction)]

        key_func: Callable[[str], str]
        if group_by == "month":
            key_func = _month_key
        elif group_by == "day":
            key_func = lambda t: t[:10]
        else:
            key_func = _year_key

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key_func(b["time"])].append(b)

        return [
            _make_result(key, group)
            for key, group in sorted(groups.items())
        ]

    # ---- 按交易类型 ----

    def get_by_type(
        self,
        transaction_type: str,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取指定交易类型的统计。

        Args:
            transaction_type: 交易类型名称，如 ``"餐饮美食"``、``"交通出行"``。
            group_by: 分组粒度。
            direction: 收支方向过滤。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            统计结果列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
            types=[transaction_type],
        )

        if group_by == "none":
            return [_make_result(transaction_type, bills, direction=direction)]

        key_func: Callable[[str], str]
        if group_by == "month":
            key_func = _month_key
        elif group_by == "day":
            key_func = lambda t: t[:10]
        else:
            key_func = _year_key

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key_func(b["time"])].append(b)

        return [
            _make_result(key, group)
            for key, group in sorted(groups.items())
        ]

    # ---- 按来源 ----

    def get_by_source(
        self,
        source: str,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取指定支付来源的统计。

        Args:
            source: 来源标识，``"alipay"`` 或 ``"wechat"``。
            group_by: 分组粒度。
            direction: 收支方向过滤。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            统计结果列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
            sources=[source],
        )

        if group_by == "none":
            return [_make_result(source, bills, direction=direction)]

        key_func: Callable[[str], str]
        if group_by == "month":
            key_func = _month_key
        elif group_by == "day":
            key_func = lambda t: t[:10]
        else:
            key_func = _year_key

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key_func(b["time"])].append(b)

        return [
            _make_result(key, group)
            for key, group in sorted(groups.items())
        ]

    # ---- 按星期 ----

    def get_by_weekday(
        self,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """按星期统计消费习惯。

        将成功交易按周一至周日分组汇总，用于分析工作日与周末的消费差异。

        Args:
            direction: 收支方向过滤，默认仅统计支出。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            按周一至周日排列的统计列表，label 为星期中文名。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        groups: dict[int, list[dict]] = defaultdict(list)
        for b in bills:
            t = _parse_time(b["time"])
            groups[t.weekday()].append(b)

        return [
            _make_result(weekday_names[wd], groups.get(wd, []))
            for wd in range(7)
        ]

    # ---- 关键词搜索 ----

    def search(
        self,
        keyword: str,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
        search_in: str = "all",
    ) -> list[dict[str, Any]]:
        """按关键词搜索账单并汇总。

        在交易对方、商品说明、交易类型等字段中匹配关键词，
        支持按时间维度分组汇总。

        Args:
            keyword: 搜索关键词（大小写不敏感）。
            group_by: 分组粒度，默认不分组。
            direction: 收支方向过滤，默认 all（不限制）。
            start: 起始日期（含）。
            end: 结束日期（含）。
            search_in: 搜索范围。``"all"`` 搜索全部文本字段，
                ``"target"`` 仅交易对方，``"description"`` 仅商品说明。

        Returns:
            匹配账单的统计结果列表。无匹配时返回空列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        kw = keyword.lower()
        matched = []
        for b in bills:
            if search_in in ("all", "target"):
                if kw in b["target"].lower():
                    matched.append(b)
                    continue
            if search_in in ("all", "description"):
                if kw in b["description"].lower():
                    matched.append(b)
                    continue
            if search_in in ("all",):
                if kw in b["type"].lower():
                    matched.append(b)
                    continue

        if group_by == "none":
            return [_make_result(f"搜索「{keyword}」", matched, direction=direction)]

        key_func: Callable[[str], str]
        if group_by == "month":
            key_func = _month_key
        elif group_by == "day":
            key_func = lambda t: t[:10]
        else:
            key_func = _year_key

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in matched:
            groups[key_func(b["time"])].append(b)

        return [
            _make_result(key, group)
            for key, group in sorted(groups.items())
        ]

    # ---- 排行榜 ----

    def get_top_targets(
        self,
        n: int = 10,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
        normalize: bool = True,
    ) -> list[dict[str, Any]]:
        """获取消费金额最高的前 N 个商户（排行）。

        Args:
            n: 返回数量。
            direction: 收支方向，默认仅统计支出。
            start: 起始日期（含）。
            end: 结束日期（含）。
            normalize: 是否对商户名做归一化处理，默认 True。

        Returns:
            按总金额降序排列的商户统计列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        key = (lambda b: normalize_target(b["target"])) if normalize else (lambda b: b["target"])

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key(b)].append(b)

        results = [
            _make_result(target, group)
            for target, group in groups.items()
        ]

        results.sort(
            key=lambda r: abs(r["total_amount"]),
            reverse=True,
        )
        return results[:n]

    def get_top_types(
        self,
        n: int = 10,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取消费金额最高的前 N 个交易类型。

        Args:
            n: 返回数量。
            direction: 收支方向，默认仅统计支出。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            按总金额降序排列的类型统计列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[b["type"]].append(b)

        results = [
            _make_result(t, group)
            for t, group in groups.items()
        ]

        results.sort(
            key=lambda r: abs(r["total_amount"]),
            reverse=True,
        )
        return results[:n]

    def get_top_sources(
        self,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """按支付来源（支付宝/微信）统计汇总。

        Args:
            direction: 收支方向，默认仅统计支出。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            按来源分组的统计列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[b["source"]].append(b)

        results = [
            _make_result(s, group)
            for s, group in groups.items()
        ]

        results.sort(
            key=lambda r: abs(r["total_amount"]),
            reverse=True,
        )
        return results

    # ---- 支付方式排行 ----

    def get_top_payment_methods(
        self,
        n: int = 10,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取使用频率/金额最高的前 N 个支付方式。

        Args:
            n: 返回数量。
            direction: 收支方向。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            按总金额降序排列的支付方式统计列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[b["payment_method"]].append(b)

        results = [
            _make_result(pm, group)
            for pm, group in groups.items()
        ]

        results.sort(
            key=lambda r: abs(r["total_amount"]),
            reverse=True,
        )
        return results[:n]

    # ---- 全部类型/商户概览 ----

    def get_all_types(
        self,
        *,
        group_by: Literal["year", "month", "day", "none"] = "none",
        direction: Literal["income", "expense", "all"] = "all",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取所有交易类型的分类统计。

        Args:
            group_by: 分组粒度。
            direction: 收支方向过滤。
            start: 起始日期（含）。
            end: 结束日期（含）。

        Returns:
            按类型分组的统计列表，按总金额降序排列。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            key = b["type"]
            if group_by != "none":
                key = f"{key}|{_month_key(b['time'])}"
            groups[key].append(b)

        results = [
            _make_result(t, group)
            for t, group in groups.items()
        ]
        results.sort(key=lambda r: abs(r["total_amount"]), reverse=True)
        return results

    def get_all_targets(
        self,
        *,
        direction: Literal["income", "expense", "all"] = "expense",
        start: str | date | datetime | None = None,
        end: str | date | datetime | None = None,
        normalize: bool = True,
        min_amount: float = 0,
    ) -> list[dict[str, Any]]:
        """获取所有商户的消费统计（不限制数量）。

        Args:
            direction: 收支方向。
            start: 起始日期（含）。
            end: 结束日期（含）。
            normalize: 是否归一化商户名。
            min_amount: 最低金额阈值，低于此值的商户不返回。

        Returns:
            按总金额降序排列的商户统计列表。
        """
        bills = _filter_bills(
            self.success_bills,
            only_success=False,
            start=start,
            end=end,
            direction=direction,
        )

        key = (lambda b: normalize_target(b["target"])) if normalize else (lambda b: b["target"])

        groups: dict[str, list[dict]] = defaultdict(list)
        for b in bills:
            groups[key(b)].append(b)

        results = [
            _make_result(t, group)
            for t, group in groups.items()
        ]
        results = [r for r in results if abs(r["total_amount"]) >= min_amount]
        results.sort(key=lambda r: abs(r["total_amount"]), reverse=True)
        return results

    # ---- 便捷输出 ----

    def print_summary(
        self,
        *,
        group_by: Literal["year", "month", "none"] = "month",
        direction: Literal["income", "expense", "all"] = "expense",
    ) -> None:
        """以表格形式打印账单总览。

        Args:
            group_by: 分组粒度。
            direction: 收支方向。
        """
        rows = self.get_summary(group_by=group_by, direction=direction)
        if not rows:
            print("无数据")
            return

        print(f"{'时间':<12} {'笔数':>6} {'总收入':>12} {'总支出':>12} {'净额':>12} {'笔均':>10}")
        print("-" * 68)
        for r in rows:
            print(
                f"{r['label']:<12} "
                f"{r['count']:>6} "
                f"{r['income']['amount']:>12.2f} "
                f"{r['expense']['amount']:>12.2f} "
                f"{r['total_amount']:>12.2f} "
                f"{r['avg_per_transaction']:>10.2f}"
            )


# ---------------------------------------------------------------------------
# CLI 入口（调试用）
# ---------------------------------------------------------------------------

def _print_table(rows: list[dict[str, Any]]) -> None:
    """以对齐表格形式打印统计结果。"""
    if not rows:
        print("（无数据）")
        return
    print(f"{'维度':<20} {'笔数':>6} {'收入':>12} {'支出':>12} {'净额':>12} {'笔均':>10}")
    print("-" * 76)
    for r in rows:
        print(
            f"{r['label']:<20} "
            f"{r['count']:>6} "
            f"{r['income']['amount']:>12.2f} "
            f"{r['expense']['amount']:>12.2f} "
            f"{r['total_amount']:>12.2f} "
            f"{r['avg_per_transaction']:>10.2f}"
        )


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="账单数据分析工具 —— 对标准化账单进行多维度统计查询",
    )

    # ---- 数据源 ----
    parser.add_argument(
        "--file", default="/tmp/analyze_bill_data.json",
        help="账单数据 JSON 文件路径（默认 /tmp/analyze_bill_data.json）",
    )
    parser.add_argument(
        "--config",
        help="分析配置文件路径（默认自动检测）。由 discover.py 生成，可人工校对后使用。",
    )

    # ---- 通用筛选条件 ----
    parser.add_argument("--start", help="起始日期，格式 YYYY-MM-DD（含）")
    parser.add_argument("--end",   help="结束日期，格式 YYYY-MM-DD（含）")
    parser.add_argument(
        "--direction", default="expense",
        choices=["expense", "income", "all"],
        help="收支方向过滤（默认 expense）",
    )
    parser.add_argument(
        "--group-by", default="none",
        choices=["month", "year", "day", "none"],
        help="时间分组粒度。用于 --summary / --by-target / --by-type / --by-source / --all-types",
    )

    # ---- 查询模式（互斥，按优先级排列）----
    parser.add_argument("--summary", action="store_true", help="总览统计")
    parser.add_argument("--by-target", metavar="NAME", help="指定商户分析（支持归一化别名）")
    parser.add_argument("--by-type", metavar="TYPE", help="指定交易类型分析（如 餐饮美食）")
    parser.add_argument("--by-source", metavar="SOURCE", help="指定来源分析（alipay / wechat）")
    parser.add_argument("--by-weekday", action="store_true", help="按星期统计消费习惯")
    parser.add_argument("--search", metavar="KEYWORD", help="关键词搜索（匹配商户名/商品说明/交易类型）")
    parser.add_argument("--top-targets", nargs="?", type=int, const=10, metavar="N",
                        help="商户消费排行，默认前 10")
    parser.add_argument("--top-types", nargs="?", type=int, const=10, metavar="N",
                        help="交易类型排行，默认前 10")
    parser.add_argument("--top-payment-methods", nargs="?", type=int, const=10, metavar="N",
                        help="支付方式排行，默认前 10")
    parser.add_argument("--all-types", action="store_true", help="全部交易类型统计")
    parser.add_argument("--all-targets", action="store_true", help="全部商户统计")
    parser.add_argument("--sources", action="store_true", help="支付来源（支付宝/微信）对比")

    # ---- 其他选项 ----
    parser.add_argument("--min-amount", type=float, default=0,
                        help="最低金额阈值，配合 --all-targets 使用")
    parser.add_argument(
        "--format", default="json", choices=["json", "table"],
        help="输出格式（默认 json）",
    )

    args = parser.parse_args()

    # ---- 加载数据 ----
    if not Path(args.file).exists():
        print(f"未找到账单数据文件: {args.file}", file=sys.stderr)
        print("请先运行 parse.py 解析账单，或通过 --file 指定正确的路径。", file=sys.stderr)
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ---- 加载配置 ----
    config: dict[str, Any] | None = None
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"未找到配置文件: {args.config}，将自动检测配置。", file=sys.stderr)
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

    analyzer = BillAnalyzer(data, config=config)

    # ---- 构建公共参数 ----
    common: dict[str, Any] = {
        "start": args.start,
        "end": args.end,
        "direction": args.direction,
    }

    # ---- 确定分组键 ----
    # 如果用户显式传了 --group-by，使用用户值；否则 summary 默认按月，其余默认不分组
    gb = args.group_by  # argparse 默认值是 "none"

    # ---- 查询分发 ----
    result: list[dict[str, Any]] = []

    if args.by_target:
        result = analyzer.get_by_target(args.by_target, group_by=gb, **common)
    elif args.by_type:
        result = analyzer.get_by_type(args.by_type, group_by=gb, **common)
    elif args.by_source:
        result = analyzer.get_by_source(args.by_source, group_by=gb, **common)
    elif args.by_weekday:
        result = analyzer.get_by_weekday(**common)
    elif args.search:
        result = analyzer.search(args.search, group_by=gb, **common)
    elif args.top_targets is not None:
        result = analyzer.get_top_targets(args.top_targets, **common)
    elif args.top_types is not None:
        result = analyzer.get_top_types(args.top_types, **common)
    elif args.top_payment_methods is not None:
        result = analyzer.get_top_payment_methods(args.top_payment_methods, **common)
    elif args.all_types:
        result = analyzer.get_all_types(group_by=gb, **common)
    elif args.all_targets:
        result = analyzer.get_all_targets(min_amount=args.min_amount, **common)
    elif args.sources:
        result = analyzer.get_top_sources(**common)
    else:
        # 默认：按月支出总览
        _gb = gb if gb != "none" else "month"
        result = analyzer.get_summary(group_by=_gb, direction=args.direction, start=args.start, end=args.end)

    # ---- 输出 ----
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_table(result)
