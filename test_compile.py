import py_compile
import sys

files = [
    "d:/Code/Tourism_Agent/app/agents/orchestrator.py",
    "d:/Code/Tourism_Agent/app/agents/planner.py",
]

for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"ERROR: {f}")
        print(e)
        sys.exit(1)

print("\nAll files compiled successfully!")
