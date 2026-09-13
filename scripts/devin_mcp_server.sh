#!/bin/sh
# Launch the mumei-agent MCP server for Devin Cloud (Customize > MCPs, STDIO).
#
# stdout must carry only JSON-RPC frames, so all server logging (stderr) is
# redirected to a log file; Devin's stdio client drops the connection during
# `initialize` when stderr is left attached.
#
# Register with the command:  /home/ubuntu/repos/mumei-agent/scripts/devin_mcp_server.sh
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${MUMEI_AGENT_MCP_LOG:-$HOME/mumei_agent_mcp.log}"
LOG_MAX_KB="${MUMEI_AGENT_MCP_LOG_MAX_KB:-10240}"

# Keep the log bounded: rotate once to "$LOG.1" when it exceeds LOG_MAX_KB.
if [ -f "$LOG" ] && [ "$(du -k "$LOG" | cut -f1)" -gt "$LOG_MAX_KB" ]; then
  mv -f "$LOG" "$LOG.1" 2>/dev/null
fi

export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
export USE_MCP_SAMPLING="${USE_MCP_SAMPLING:-true}"

cd "$REPO_DIR" || exit 1
exec uv run python -m agent mcp-server 2>>"$LOG"
