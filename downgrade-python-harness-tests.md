I cannot write the file. The execution sandbox is read-only (workspace NOT writable). Here is the plan. Save it with the command at the end.
Plan: Remove the nested Pi harness wrapper from the pytest suite
Objective
Make the benchmark flow run the direct Pi harness. Remove test wrappers that add no independent coverage.
Background
- tests/test_pi_extension.py::DirectPiExtensionTests is a nested harness:
 unittest → subprocess → scripts/pi_extension_smoke.py → bun --smol run .../cli.ts.
- scripts/pi_extension_smoke.py already validates:
 1. exit code 0,
 2. Pi version 0.85.1,
 3. tool order,
 4. audit length,
 5. credential-free result,
 6. board_read observation.
- The unittest wrapper repeats these checks. It adds no new coverage.
Changes
1. Remove the file tests/test_pi_extension.py.
 - Alternative: add @unittest.skip("Direct harness runs separately") to the class.
2. Keep scripts/pi_extension_smoke.py as the only direct-harness entrypoint.
3. Keep these files. They use fake agents and unit fixtures. They verify wiring and audit handling without launching Pi:
 - tests/test_board_storage.py
 - tests/test_runtime.py
 - tests/test_tool_service.py
4. Do not change scripts/test. Unittest discovery then runs 50 tests instead of 51.
Benchmark invocation
Run the direct harness:

python scripts/pi_extension_smoke.py


Write a trace file:

python scripts/pi_extension_smoke.py --output artifacts/pi-smoke.json


Preconditions:
- bun is on PATH.
- APART_PI_ROOT points to a Pi checkout that contains packages/coding-agent/src/cli.ts.
Verification
1. Run scripts/test.
2. Confirm 50 tests pass and the suite spawns no Pi process.
3. Run python scripts/pi_extension_smoke.py.
4. Confirm exit code 0 and the JSON trace matches the pinned version and tool sequence.
Optional tracking
If you use chainlink, open one issue:
Remove nested Pi harness wrapper from pytest suite with label removed.


Save it with:


cat > /home/framework/Workspace/apart-incident-response/docs/refactor-pytest-harness.md 
EOF


Delete tests/test_pi_extension.py; keep scripts/pi_extension_smoke.py as the direct benchmark entrypoint; leave the unit and fake-agent tests in place.