#!/usr/bin/env bash
set -euo pipefail
BASE="http://127.0.0.1:8000"
die(){ echo "❌ $*" >&2; exit 1; }

ALICIA_TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)
[ -n "${ALICIA_TOKEN:-}" ] && [ "$ALICIA_TOKEN" != "null" ] || die "Login failed"

echo "== Get newest raid_report message =="
MSG_ID=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/inbox?limit=1&kind=raid_report" | jq -r '.messages[0].id // empty')
[[ "$MSG_ID" =~ ^[0-9]+$ ]] || die "No raid_report message found to delete"
echo "msg_id=$MSG_ID"

echo "== Delete it =="
curl -sS -X DELETE -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/$MSG_ID" | jq .

echo "== Verify 404 on read =="
STATUS=$(curl -sS -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/$MSG_ID")
[ "$STATUS" = "404" ] || die "Expected 404 after delete, got $STATUS"

echo "✅ Mail delete UI-test passed"
