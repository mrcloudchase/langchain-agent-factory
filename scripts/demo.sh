#!/usr/bin/env bash
# Narrated CLI walkthrough, recorded with asciinema for the README.
#   asciinema rec --cols 110 --rows 34 -c scripts/demo.sh demo/cli.cast
set -euo pipefail
cd "$(dirname "$0")/.."
P() { [ -n "${DEMO_FAST:-}" ] || sleep "${1:-2}"; }
say() { printf '\n\033[1;36m# %s\033[0m\n' "$*"; P 1.3; }
run() { printf '\033[1;32m$ %s\033[0m\n' "$*"; P 0.7; "$@" || true; P 2.2; }
clear
printf '\033[1mAgent Factory\033[0m  -  the organization defines agents and the path to production; teams create from templates\n'
printf 'mode: \033[1;33moffline (scripted replay, no keys)\033[0m\n'; P 3
say "1. What the organization owns: templates, a published tool catalog, processes"
run factory templates
run factory tools
say "2. A team creates an agent from a template. Policy runs before anything is kept."
run factory new claims_demo --template claims_processing --owner ops-analyst@halcyon.example --display "Claims Demo"
say "   The wrong team is refused with the rule"
run factory new claims_for_research --template claims_processing --team research --owner research-lead@halcyon.example
say "3. Run it: a workflow with four steps; recording the decision pauses for a human"
run factory run claims_demo "Claim: policy P-1007, stolen laptop from a locked car on 2026-09-28, amount \$3,100, police report attached." --approve
say "4. The gate: evaluators, thresholds, regression checks"
run factory eval claims_demo
say "5. Promotion follows the process: dev -> staging on policy and evals"
run factory promote claims_demo --by ops-analyst@halcyon.example
say "   staging -> production needs an ops approver and a platform approver"
factory promote claims_demo --by ops-analyst@halcyon.example | tee /tmp/factory-promo.txt
RID=$(grep -oE "request id: [a-f0-9]+" /tmp/factory-promo.txt | awk '{print $3}')
P 2
say "   A builder cannot approve; the ops lead and the platform lead can"
run factory approve claims_demo "$RID" --as ops-analyst@halcyon.example
run factory approve claims_demo "$RID" --as ops-lead@halcyon.example
run factory approve claims_demo "$RID" --as platform-lead@halcyon.example
say "6. The catalog"
run factory list
say "Console: langgraph dev, then http://localhost:2024/console"
P 3
factory remove claims_demo --yes >/dev/null 2>&1 || true
