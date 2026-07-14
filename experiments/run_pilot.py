from app.core.experiment_runner import ExperimentRunner


if __name__ == "__main__":

    runner = ExperimentRunner()

    results = runner.run_benchmark(
        "experiments/benchmark_test.json",
        methods=[
            "llm_direct",
            "single_agent",
            "full_system"
        ]
    )

    print("实验完成！")

    for item in results:
        print(
            item["case_id"],
            item["method"],
            item["status"]
        )