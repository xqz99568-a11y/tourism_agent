import csv
from pathlib import Path

from app.core.plain_language_review import (
    build_plain_review_row,
    write_plain_review_batches,
)


def _review_row(index: int, *, machine_status: str = "passed") -> dict[str, str]:
    return {
        "row_index": str(index),
        "review_unit_id": f"ctp_test_{index:03d}",
        "task_type": "trip_planning",
        "city_id": "beijing",
        "user_input": "北京2天2人旅行，预算4800元。",
        "gold_slots_json": (
            '{"destination":"beijing","duration_days":2,'
            '"people_count":2,"budget_amount":4800}'
        ),
        "parsed_slots_json": (
            '{"destination":"beijing","duration_days":2,'
            '"people_count":2,"budget_amount":4800}'
        ),
        "current_parsed_slots_json": (
            '{"destination":"beijing","duration_days":2,'
            '"people_count":2,"budget_amount":4800}'
        ),
        "parse_gold_match": "True",
        "changed_slots_json": "{}",
        "preserved_slots_json": "{}",
        "required_tools": "poi_search,weather_query,budget_calculator",
        "accepted_agent_sets_json": (
            '[["attraction","weather","itinerary","budget"]]'
        ),
        "accepted_tool_sets_json": (
            '[["poi_search","weather_query","budget_calculator"]]'
        ),
        "offline_feasibility_status": "passed",
        "machine_review_status": machine_status,
        "human_review_status": "pending_human_confirmation",
        "human_reviewer": "",
        "human_decision": "",
        "human_notes": "",
    }


def test_plain_review_row_uses_chinese_labels_and_never_prefills_approval() -> None:
    plain = build_plain_review_row(_review_row(1))

    assert plain["编号"] == "001｜ctp_test_001"
    assert "完整旅游规划" in plain["任务类型"]
    assert "城市：北京（自动解析一致）" in plain["城市/日期/人数/天数/预算"]
    assert "景点 Agent" in plain["需要的Agent"]
    assert "景点查询工具" in plain["需要的工具"]
    assert plain["你的决定"] == "□ 通过　　□ 需要修改"
    assert "approved" not in plain["你的决定"].lower()


def test_plain_review_batches_write_exact_batch_sizes(tmp_path: Path) -> None:
    csv_path = tmp_path / "review.csv"
    rows = [_review_row(index) for index in range(1, 21)]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    output_dir = tmp_path / "batches"
    result = write_plain_review_batches(
        review_csv_path=csv_path,
        output_dir=output_dir,
        batch_size=10,
        expected_rows=20,
    )

    assert result["row_count"] == 20
    assert result["batch_count"] == 2
    batch_files = sorted(output_dir.glob("第*.md"))
    assert [path.name for path in batch_files] == [
        "第01批_001-010.md",
        "第02批_011-020.md",
    ]
    assert (output_dir / "00_审核说明与进度.md").exists()
    first_batch = batch_files[0].read_text(encoding="utf-8")
    assert first_batch.count("| 编号 |") == 10
    assert "第01批：本批全部通过" in first_batch
