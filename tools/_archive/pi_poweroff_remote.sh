echo "shutting down $(hostname) at $(date +%T)"; sync; (sleep 2; sudo -n systemctl poweroff) >/dev/null 2>&1 &
