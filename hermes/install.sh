#!/usr/bin/env bash
#
# install.sh — Hermes Skill installer for Obsidian RAG Protocol
#
# Idempotent: safe to run multiple times. Creates the hermes skill directory,
# copies the rebuild script into place, configures paths, and sets up a daily
# cron job for automatic index rebuilding.
#
# Usage:
#   bash install.sh                          # interactive — prompts for paths
#   bash install.sh --vault ~/Documents/Vault --output ~/.hermes/vault-index.json --scan "wiki/projects:cc wiki/career:cc hermes-knowledge/:hermes"
#   bash install.sh --uninstall              # remove cron job and installed files
#
set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${BLUE}ℹ${RESET} $*"; }
ok()    { echo -e "${GREEN}✔${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET} $*"; }
err()   { echo -e "${RED}✖${RESET} $*" >&2; }
die()   { err "$@"; exit 1; }

# ─── Defaults ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VAULT_PATH=""
OUTPUT_PATH=""
SCAN_DIRS=""
INDEX_DIR=""
CRON_HOUR=9
CRON_MINUTE=0
UNINSTALL=false

# ─── Parse flags ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)       VAULT_PATH="$2"; shift 2 ;;
    --output)      OUTPUT_PATH="$2"; shift 2 ;;
    --scan)        SCAN_DIRS="$2"; shift 2 ;;
    --cron-hour)   CRON_HOUR="$2"; shift 2 ;;
    --cron-minute)  CRON_MINUTE="$2"; shift 2 ;;
    --uninstall)   UNINSTALL=true; shift ;;
    -h|--help)
      echo "Usage: bash install.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --vault PATH        Path to Obsidian vault root"
      echo "  --output PATH       Path for vault-index.json output"
      echo "  --scan DIRS         Scan dirs (space-separated, format: DIR:AUTHOR or DIR)"
      echo "  --cron-hour HOUR    Daily cron hour (0-23, default: 9)"
      echo "  --cron-minute MIN   Daily cron minute (0-59, default: 0)"
      echo "  --uninstall         Remove cron job and installed files"
      echo "  -h, --help          Show this help"
      exit 0
      ;;
    *) die "Unknown option: $1. Run with --help for usage." ;;
  esac
done

# ─── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == true ]]; then
  info "Uninstalling Obsidian RAG Protocol skill..."

  # Remove cron job
  if crontab -l 2>/dev/null | grep -q "rebuild-vault-index"; then
    crontab -l 2>/dev/null | grep -v "rebuild-vault-index" | crontab -
    ok "Removed cron job."
  else
    warn "No ORP cron job found in crontab."
  fi

  # Remove installed rebuild script
  INSTALL_BIN="${HOME}/.hermes/bin/rebuild-vault-index.py"
  if [[ -f "$INSTALL_BIN" ]]; then
    rm -f "$INSTALL_BIN"
    ok "Removed $INSTALL_BIN"
  fi

  # Remove Hermes skill directory
  SKILL_DIR="${HOME}/.hermes/skills/obsidian-rag"
  if [[ -d "$SKILL_DIR" ]]; then
    rm -rf "$SKILL_DIR"
    ok "Removed skill directory $SKILL_DIR"
  fi

  echo ""
  ok "Uninstall complete. The vault index file was NOT removed (it may still be useful)."
  echo "  Index location: ${OUTPUT_PATH:-~/.hermes/vault-index.json}"
  exit 0
fi

# ─── Interactive prompts (if needed) ─────────────────────────────────────────
if [[ -z "$VAULT_PATH" ]]; then
  echo -e "${BOLD}Obsidian RAG Protocol — Installer${RESET}"
  echo ""
  echo "This script will:"
  echo "  1. Copy rebuild-vault-index.py to ~/.hermes/bin/"
  echo "  2. Install the Hermes skill to ~/.hermes/skills/obsidian-rag/"
  echo "  3. Configure paths in the skill"
  echo "  4. Set up a daily cron job for index rebuilding"
  echo ""
  read -rp "Path to your Obsidian vault [~/Documents/Obsidian]: " VAULT_INPUT
  VAULT_PATH="${VAULT_INPUT//\$HOME/$HOME}"
  VAULT_PATH="${VAULT_PATH//\~/$HOME}"
  [[ -z "$VAULT_PATH" ]] && VAULT_PATH="$HOME/Documents/Obsidian"
fi

# Expand paths
VAULT_PATH="${VAULT_PATH//\~/$HOME}"
VAULT_PATH="$(cd "$VAULT_PATH" 2>/dev/null && pwd || echo "$VAULT_PATH")"

if [[ ! -d "$VAULT_PATH" ]]; then
  die "Vault directory not found: $VAULT_PATH. Please check the path and try again."
fi
ok "Vault path: $VAULT_PATH"

if [[ -z "$OUTPUT_PATH" ]]; then
  OUTPUT_PATH="$HOME/.hermes/vault-index.json"
fi
OUTPUT_PATH="${OUTPUT_PATH//\~/$HOME}"

if [[ -z "$SCAN_DIRS" ]]; then
  echo ""
  echo "Scan directories specify which subdirectories of the vault to index."
  echo "Format: DIR:AUTHOR or just DIR (default author: unknown)"
  echo "Example: wiki/projects:cc wiki/career:cc hermes-knowledge/:hermes"
  echo ""
  read -rp "Scan directories: " SCAN_INPUT
  SCAN_DIRS="$SCAN_INPUT"
  [[ -z "$SCAN_DIRS" ]] && SCAN_DIRS="wiki:unknown"
fi

# ─── Step 1: Install all utilities ─────────────────────────────────────────────
info "Installing ORP utilities..."

INSTALL_BIN="$HOME/.hermes/bin"
mkdir -p "$INSTALL_BIN"

# All single-file utilities the spec ships. Each is independent and can be
# invoked standalone; bundling them at install time avoids the "user only
# discovers tool X exists 6 months later" failure mode.
UTILITIES=(
  "rebuild-vault-index.py"
  "orp_reader.py"
  "orp_health.py"
  "orp_link_check.py"
  "expand_aliases.py"
  "convert_bare_to_fullpath.py"
)

for util in "${UTILITIES[@]}"; do
  SOURCE="$REPO_ROOT/$util"
  if [[ ! -f "$SOURCE" ]]; then
    warn "Utility $util not found at $SOURCE — skipping"
    continue
  fi
  cp "$SOURCE" "$INSTALL_BIN/$util"
  chmod +x "$INSTALL_BIN/$util"
  ok "Installed $util to $INSTALL_BIN/$util"
done

# ─── Step 2: Install Hermes skill ────────────────────────────────────────────
info "Installing Hermes skill..."

SKILL_DIR="$HOME/.hermes/skills/obsidian-rag"
mkdir -p "$SKILL_DIR"

SOURCE_SKILL="$SCRIPT_DIR/SKILL.md"
if [[ ! -f "$SOURCE_SKILL" ]]; then
  die "SKILL.md not found at $SOURCE_SKILL. Make sure it exists in the hermes/ directory."
fi

# Copy skill and inject configured paths
SKILL_DEST="$SKILL_DIR/SKILL.md"
cp "$SOURCE_SKILL" "$SKILL_DEST"

# Replace the default index path with the configured output path
if [[ "$OUTPUT_PATH" != "$HOME/.hermes/vault-index.json" ]]; then
  # macOS sed needs -i '' for in-place edit
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|~/.hermes/vault-index.json|$OUTPUT_PATH|g" "$SKILL_DEST"
  else
    sed -i "s|~/.hermes/vault-index.json|$OUTPUT_PATH|g" "$SKILL_DEST"
  fi
  ok "Updated index path in skill to $OUTPUT_PATH"
fi

ok "Installed skill to $SKILL_DIR/SKILL.md"

# ─── Step 3: Create output directory and run initial build ────────────────────
INDEX_DIR="$(dirname "$OUTPUT_PATH")"
mkdir -p "$INDEX_DIR"

info "Running initial index build..."

# Build the --scan arguments
SCAN_ARGS=""
for dir_spec in $SCAN_DIRS; do
  SCAN_ARGS="$SCAN_ARGS $dir_spec"
done

PYTHON_CMD="python3"
if ! command -v python3 &>/dev/null; then
  if command -v python &>/dev/null; then
    PYTHON_CMD="python"
  else
    die "Python 3 not found. Please install Python 3.8+ and re-run this script."
  fi
fi

BUILD_CMD="$PYTHON_CMD $INSTALL_BIN/rebuild-vault-index.py --vault $VAULT_PATH --output $OUTPUT_PATH --scan$SCAN_ARGS"

if $BUILD_CMD; then
  ok "Initial index build succeeded."
else
  warn "Initial build failed. This may be normal if vault subdirectories haven't been created yet."
  warn "The cron job will retry daily. You can also run manually:"
  echo "  $BUILD_CMD"
fi

# ─── Step 4: Set up daily cron job ───────────────────────────────────────────
info "Setting up daily cron job (runs at $CRON_HOUR:$CRON_MINUTE)..."

CRON_CMD="$PYTHON_CMD $INSTALL_BIN/rebuild-vault-index.py --vault $VAULT_PATH --output $OUTPUT_PATH --scan$SCAN_ARGS >> $HOME/.hermes/orp-cron.log 2>&1"

# Remove any existing ORP cron entry (idempotent)
if crontab -l 2>/dev/null | grep -q "rebuild-vault-index"; then
  crontab -l 2>/dev/null | grep -v "rebuild-vault-index" | crontab -
  info "Removed previous ORP cron job."
fi

# Add new cron entry
(crontab -l 2>/dev/null; echo "$CRON_MINUTE $CRON_HOUR * * * $CRON_CMD") | crontab -
ok "Cron job installed: runs daily at $CRON_HOUR:$CRON_MINUTE"

# ─── Step 5: Write config file for reference ─────────────────────────────────
CONFIG_FILE="$HOME/.hermes/orp-config.sh"
cat > "$CONFIG_FILE" <<EOF
# Obsidian RAG Protocol Configuration
# Generated by install.sh — edit manually if needed
VAULT_PATH="$VAULT_PATH"
OUTPUT_PATH="$OUTPUT_PATH"
SCAN_DIRS="$SCAN_DIRS"
REBUILD_SCRIPT="$INSTALL_BIN/rebuild-vault-index.py"
PYTHON_CMD="$PYTHON_CMD"
CRON_SCHEDULE="$CRON_MINUTE $CRON_HOUR * * *"
INSTALLED_ON="$(date -Iseconds 2>/dev/null || date)"
EOF

ok "Config saved to $CONFIG_FILE"

# ─── Verification ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Obsidian RAG Protocol — Installation Complete${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "  Vault:           $VAULT_PATH"
echo "  Index output:    $OUTPUT_PATH"
echo "  Scan directories: $SCAN_DIRS"
echo "  Rebuild script:  $INSTALL_BIN/rebuild-vault-index.py"
echo "  Skill location:  $SKILL_DIR/SKILL.md"
echo "  Config file:     $CONFIG_FILE"
echo "  Cron schedule:   Daily at $CRON_HOUR:$CRON_MINUTE"
echo "  Cron log:         $HOME/.hermes/orp-cron.log"
echo ""
echo -e "${BOLD}Verification steps:${RESET}"
echo ""
echo "  1. Check the index was built:"
echo "     $PYTHON_CMD -c \"import json; d=json.load(open('$OUTPUT_PATH')); print(f'{len(d[\\\"entries\\\"])} entries, updated: {d[\\\"updated\\\"]}')\""
echo ""
echo "  2. Test incremental rebuild (should show 0 changed):"
echo "     $BUILD_CMD"
echo ""
echo "  3. Verify the cron job:"
echo "     crontab -l | grep rebuild-vault-index"
echo ""
echo "  4. Test with your agent:"
echo "     Ask: \"What were we working on recently?\""
echo "     The agent should read $OUTPUT_PATH and match relevant notes."
echo ""
echo -e "${BOLD}To uninstall later:${RESET}"
echo "  bash $SCRIPT_DIR/install.sh --uninstall"
echo ""
ok "Done! Your agent now has persistent vault memory."