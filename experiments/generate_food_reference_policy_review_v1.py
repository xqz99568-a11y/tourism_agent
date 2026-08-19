"""Generate review materials for the food reference policy.

This script only creates human-review files. It does not freeze new food
constants and does not mutate the formal dataset.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.fixed_data import FIXED_CITY_IDS


DEFAULT_OUTPUT_MD = ROOT / "experiments" / "generated" / "food_reference_policy_review_v1.md"
DEFAULT_OUTPUT_CSV = ROOT / "experiments" / "generated" / "food_reference_policy_review_v1.csv"
TIERS = ("economy", "comfort", "premium")


def generate_food_reference_policy_review(
    *,
    output_md: str | Path = DEFAULT_OUTPUT_MD,
    output_csv: str | Path = DEFAULT_OUTPUT_CSV,
) -> List[Dict[str, Any]]:
    rows = _build_rows()
    _write_csv(rows, Path(output_csv))
    _write_md(rows, Path(output_md))
    return rows


def _build_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for city_id in FIXED_CITY_IDS:
        document = _read_json(ROOT / "data" / "restaurants" / f"{city_id}.json")
        areas = document.get("dining_areas") or []
        medians = {
            tier: _median(_tier_values(areas, tier, "reference_price_cny"))
            for tier in TIERS
        }
        economy_median = medians.get("economy") or 0.0
        for tier in TIERS:
            refs = _tier_values(areas, tier, "reference_price_cny")
            mins = _tier_values(areas, tier, "minimum_price_cny")
            median_ref = _median(refs)
            mean_ref = round(statistics.mean(refs), 2) if refs else 0.0
            current_2_people_2_days_1_night_cost = round(median_ref * 2 * (2 * 2 + 0.5 * 1), 2)
            example_average_per_person_day = round(current_2_people_2_days_1_night_cost / 2 / 2, 2)
            suggested_breakfast = round(_median(mins), 2)
            suggested_lunch = round(median_ref, 2)
            suggested_dinner = round(median_ref, 2)
            full_three_meal_day_reference = round(
                suggested_breakfast + suggested_lunch + suggested_dinner,
                2,
            )
            suggested_2_people_2_days_1_night_cost = round(
                2 * (suggested_breakfast * 1 + suggested_lunch * 2 + suggested_dinner * 2),
                2,
            )
            same_scenario_difference = round(
                suggested_2_people_2_days_1_night_cost - current_2_people_2_days_1_night_cost,
                2,
            )
            same_scenario_difference_ratio = (
                round(same_scenario_difference / current_2_people_2_days_1_night_cost, 4)
                if current_2_people_2_days_1_night_cost
                else None
            )
            rows.append(
                {
                    "city_id": city_id,
                    "city_name": (document.get("metadata") or {}).get("city_name") or city_id,
                    "tier": tier,
                    "area_reference_prices": refs,
                    "mean_reference_price": mean_ref,
                    "median_reference_price": round(median_ref, 2),
                    "example_2d1n_average_per_person_day_cost": example_average_per_person_day,
                    "current_2_people_2_days_1_night_cost": current_2_people_2_days_1_night_cost,
                    "suggested_breakfast_cost": suggested_breakfast,
                    "suggested_lunch_cost": suggested_lunch,
                    "suggested_dinner_cost": suggested_dinner,
                    "full_three_meal_day_reference_cost": full_three_meal_day_reference,
                    "suggested_2_people_2_days_1_night_cost": suggested_2_people_2_days_1_night_cost,
                    "same_scenario_difference": same_scenario_difference,
                    "same_scenario_difference_ratio": same_scenario_difference_ratio,
                    "tier_multiplier": round(median_ref / economy_median, 2) if economy_median else None,
                    "anomaly_note": _anomaly_note(tier),
                }
            )
    return rows


def _tier_values(areas: Iterable[Dict[str, Any]], tier: str, field: str) -> List[float]:
    values = []
    for area in areas:
        value = (((area.get("budget") or {}).get("tiers") or {}).get(tier) or {}).get(field)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return values


def _median(values: Iterable[float]) -> float:
    values = sorted(float(value) for value in values if float(value) > 0)
    if not values:
        return 0.0
    return float(statistics.median(values))


def _anomaly_note(tier: str) -> str:
    if tier == "economy":
        return "已人工确认：进入正式主实验经济型预算基线"
    return "不进入正式主实验确认范围：仅作开发检查或后续扩展参考"


def _write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "city_id",
        "city_name",
        "tier",
        "area_reference_prices",
        "mean_reference_price",
        "median_reference_price",
        "example_2d1n_average_per_person_day_cost",
        "current_2_people_2_days_1_night_cost",
        "suggested_breakfast_cost",
        "suggested_lunch_cost",
        "suggested_dinner_cost",
        "full_three_meal_day_reference_cost",
        "suggested_2_people_2_days_1_night_cost",
        "same_scenario_difference",
        "same_scenario_difference_ratio",
        "tier_multiplier",
        "anomaly_note",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _compact(row.get(key)) for key in fieldnames})


def _write_md(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table_rows = [
        [
            row["city_name"],
            row["tier"],
            row["area_reference_prices"],
            row["mean_reference_price"],
            row["median_reference_price"],
            row["example_2d1n_average_per_person_day_cost"],
            row["current_2_people_2_days_1_night_cost"],
            row["suggested_breakfast_cost"],
            row["suggested_lunch_cost"],
            row["suggested_dinner_cost"],
            row["full_three_meal_day_reference_cost"],
            row["suggested_2_people_2_days_1_night_cost"],
            row["same_scenario_difference"],
            _ratio_percent(row["same_scenario_difference_ratio"]),
            row["tier_multiplier"],
            row["anomaly_note"],
        ]
        for row in rows
    ]
    comparison_rows = [
        [
            row["city_name"],
            row["tier"],
            row["current_2_people_2_days_1_night_cost"],
            row["suggested_2_people_2_days_1_night_cost"],
            row["same_scenario_difference"],
            _ratio_percent(row["same_scenario_difference_ratio"]),
            _review_conclusion(row),
        ]
        for row in rows
    ]
    text = "\n".join(
        [
            "# Food Reference Policy Review v1",
            "",
            "> 本文件只用于人工审阅餐饮参考策略，不冻结最终餐饮常量，也不修改正式题库。",
            "",
            "## 生成原则",
            "",
            "- 所有原始参考价均来自 `data/restaurants/*.json` 的冻结餐饮区域数据。",
            "- “两天一晚示例的人均日均餐饮费”固定为 `current_2_people_2_days_1_night_cost / 2人 / 2天`，只用于展示 2 人、2 天、1 晚场景下的日均摊销结果。",
            "- 当前方案同场景总额公式：`median_reference_price * 2 * (2 * 2 + 0.5 * 1)`。",
            "- 建议早餐/午餐/晚餐费用只作为审阅建议：早餐取该档 minimum_price 的城市中位数，午餐和晚餐取该档 reference_price 的城市中位数。",
            "- “完整三餐日参考费用”固定为 `suggested_breakfast_cost + suggested_lunch_cost + suggested_dinner_cost`。该字段表示完整三餐日费用，不能与“两天一晚示例的人均日均餐饮费”直接比较。",
            "- 建议方案同场景总额公式：`2 * (suggested_breakfast_cost * 1 + suggested_lunch_cost * 2 + suggested_dinner_cost * 2)`。",
            "- 正式主实验采用当前经济档公式作为冻结实验参考规则；五个城市 economy 餐饮参考值已在 `economy_budget_manual_review_v1.json` 中确认。",
            "- comfort/premium 不属于本次正式主实验预算金标确认范围，只保留为开发检查或后续扩展研究材料。",
            "",
            "## 审阅表",
            "",
            _markdown_table(
                [
                    "城市",
                    "档次",
                    "所有餐饮区域参考价",
                    "均值",
                    "中位数",
                    "两天一晚示例的人均日均餐饮费",
                    "当前2人2天1晚总额",
                    "建议早餐",
                    "建议午餐",
                    "建议晚餐",
                    "完整三餐日参考费用",
                    "建议2人2天1晚总额",
                    "同口径差额",
                    "同口径差额比例",
                    "档次倍率",
                    "异常说明",
                ],
                table_rows,
            ),
            "",
            "## 同口径比较表",
            "",
            "> 本表统一按 2 个人、2 天、1 晚比较当前方案与建议方案；差额比例 = 差额 / 当前2人2天1晚总额。",
            "",
            _markdown_table(
                [
                    "城市",
                    "档次",
                    "当前2人2天1晚总额",
                    "建议2人2天1晚总额",
                    "差额",
                    "差额比例",
                    "审阅结论",
                ],
                comparison_rows,
            ),
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def _ratio_percent(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def _review_conclusion(row: Dict[str, Any]) -> str:
    if row.get("tier") == "economy":
        return "已确认进入正式主实验经济型预算基线"
    difference = float(row.get("same_scenario_difference") or 0.0)
    if abs(difference) < 0.01:
        return "不进入正式主实验确认范围，仅作参考"
    if difference > 0:
        return "建议方案同口径更高，但不进入正式主实验确认范围"
    return "建议方案同口径更低，但不进入正式主实验确认范围"


def _markdown_table(headers: List[str], rows: List[List[Any]]) -> str:
    def cell(value: Any) -> str:
        return _compact(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(lines)


def _compact(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    args = parser.parse_args()
    rows = generate_food_reference_policy_review(
        output_md=args.output_md,
        output_csv=args.output_csv,
    )
    print(
        json.dumps(
            {
                "output_md": args.output_md,
                "output_csv": args.output_csv,
                "rows": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
