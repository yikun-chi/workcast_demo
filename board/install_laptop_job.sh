#!/usr/bin/env bash
# Install the board's scheduled job on the laptop. launchd cannot run scripts from ~/Documents, so the script is copied out.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p "$HOME/.workcast_board_publish"
cp publish_from_laptop.sh "$HOME/.workcast_board_publish/publish_from_laptop.sh"
chmod +x "$HOME/.workcast_board_publish/publish_from_laptop.sh"
launchctl unload "$HOME/Library/LaunchAgents/com.workcast.board.publish.plist" 2>/dev/null || true
cp com.workcast.board.publish.plist "$HOME/Library/LaunchAgents/com.workcast.board.publish.plist"
launchctl load "$HOME/Library/LaunchAgents/com.workcast.board.publish.plist"
echo installed
