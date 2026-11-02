#!/bin/bash
cd "$(dirname "$0")/../.."
export NODE_PATH="${NODE_PATH:-$(npm root -g)}"
status=0
for test in tests/e2e/${1:-*}.e2e.js; do
    echo "== $test"
    node "$test" || status=1
done
exit $status
