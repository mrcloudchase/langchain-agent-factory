#!/usr/bin/env bash
# The platform team's view: the org is code in org/, and `factory check` guards every change.
# Recorded for the README with: asciinema rec -c scripts/platform_demo.sh demo/platform.cast
set -euo pipefail
cd "$(dirname "$0")/.."
export FACTORY_OFFLINE=1 COLUMNS=100

say() { printf '\n\033[1;36m# %s\033[0m\n' "$*"; sleep 1.2; }
run() { printf '\033[1;32m$\033[0m %s\n' "$*"; sleep 0.6; eval "$@"; sleep 1.8; }

say "Priya, platform lead: the org is defined as code"
run "find org -type f | sort"
say "A template fixes tools, approvals, limits, evals and the path to production"
run "sed -n '1,30p' org/templates/support_agent/template.yaml"
say "What builders can pick from"
run "factory templates"
run "factory tools"
run "factory processes"
say "CI runs factory check on every pull request to org/"
run "factory check"

say "A pull request that drops the approval on refunds..."
broken=$(mktemp -d /tmp/pr-branch.XXXX)
cp -r org data "$broken"
sed -i 's/^approvals: \[issue_refund\]/approvals: []/' "$broken/org/templates/support_agent/template.yaml"
run "diff org/templates/support_agent/template.yaml $broken/org/templates/support_agent/template.yaml || true"
say "...fails the check, so it cannot merge"
run "FACTORY_ROOT=$broken factory check || true"
rm -rf "$broken"
