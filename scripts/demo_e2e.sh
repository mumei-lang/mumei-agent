#!/usr/bin/env bash
# =============================================================================
# Mumei Agent E2E Demo Script
#
# Records a full self-healing cycle: verification failure → LLM fix → success.
# Can be run directly or recorded with asciinema:
#
#   asciinema rec demo.cast -c "bash scripts/demo_e2e.sh"
#   # Then upload: asciinema upload demo.cast
#   # Or render as GIF: agg demo.cast docs/demo.gif
#
# Prerequisites:
#   - mumei CLI in PATH (or MUMEI_BIN set in .env)
#   - Ollama running (docker compose up -d)
#   - Model pulled (docker exec mumei-ollama ollama pull qwen3.5)
#   - pip install -r requirements.txt
# =============================================================================
set -euo pipefail

DEMO_DIR="$(mktemp -d)"
EXAMPLE_FILE="examples/sword_test.mm"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║        🗡️  Mumei Agent — E2E Self-Healing Demo          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- Step 1: Show the buggy source ---
echo "━━━ Step 1: Buggy source file ━━━"
echo ""
cp "$EXAMPLE_FILE" "$DEMO_DIR/sword_test.mm"
cat "$DEMO_DIR/sword_test.mm"
echo ""
echo "⚠  Problem: requires only 'a >= 0', but division by zero is possible"
echo "   when b == 0. Z3 will find a counter-example."
echo ""
sleep 2

# --- Step 2: Run mumei verify to show the failure ---
echo "━━━ Step 2: Verification (mumei build) ━━━"
echo ""
echo "\$ mumei build $DEMO_DIR/sword_test.mm -o katana"
echo ""
if mumei build "$DEMO_DIR/sword_test.mm" -o katana 2>&1; then
    echo "  (Unexpected: build succeeded. The example may need updating.)"
else
    echo ""
    echo "❌ Verification failed — as expected."
fi
echo ""
sleep 2

# --- Step 3: Show the report ---
echo "━━━ Step 3: Verification report ━━━"
echo ""
if [ -f report.json ]; then
    python3 -m json.tool report.json 2>/dev/null || cat report.json
elif [ -f "$DEMO_DIR/report.json" ]; then
    python3 -m json.tool "$DEMO_DIR/report.json" 2>/dev/null || cat "$DEMO_DIR/report.json"
else
    echo "  (report.json not found — mumei may output it differently)"
fi
echo ""
sleep 2

# --- Step 4: Run the self-healing loop ---
echo "━━━ Step 4: Self-Healing Loop ━━━"
echo ""
echo "\$ python -m agent.self_healing $DEMO_DIR/sword_test.mm --max-retries 3"
echo ""
python -m agent.self_healing "$DEMO_DIR/sword_test.mm" --max-retries 3
echo ""
sleep 1

# --- Step 5: Show the fixed source ---
echo "━━━ Step 5: Fixed source file ━━━"
echo ""
cat "$DEMO_DIR/sword_test.mm"
echo ""

# --- Step 6: Show diff ---
echo "━━━ Step 6: Diff (original → fixed) ━━━"
echo ""
diff --color=always "$DEMO_DIR/sword_test.mm.bak" "$DEMO_DIR/sword_test.mm" || true
echo ""

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Self-healing complete! The blade is reforged.      ║"
echo "╚══════════════════════════════════════════════════════════╝"

# Cleanup
rm -rf "$DEMO_DIR"
