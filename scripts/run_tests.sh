# scripts/run_tests.sh
#!/usr/bin/env bash
set -euo pipefail

run() {
  local name="$1"
  echo
  echo "=============================="
  echo "RUN: $name"
  echo "=============================="
  "./scripts/$name"
}

run "test_seed.sh"
run "train_testing.sh"
run "train_buildings_rules_testing.sh"
run "train_queue_testing.sh"
run "train_queue_cancel_testing.sh"
run "train_queue_pagination_testing.sh"
run "mail_flow_testing.sh"
run "mail_pagination_testing.sh"
run "mail_delete_testing.sh"
run "mail_toggle_delete_testing.sh"

echo
echo "✅ all tests passed"
