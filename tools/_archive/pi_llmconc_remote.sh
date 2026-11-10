H=http://127.0.0.1:11435; J='-H Content-Type:application/json'
B='{"model":"qwen3:1.7b","messages":[{"role":"user","content":"Count from one to eight in English words."}],"stream":false,"think":false,"options":{"num_predict":40}}'
echo "===SEQUENTIAL x3==="; for i in 1 2 3; do S=$(date +%s.%N); R=$(curl -s -m 60 $J $H/api/chat -d "$B" | head -c 160); echo "[$i] $(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s $R"; done
echo "===PARALLEL x2==="; (S=$(date +%s.%N); R=$(curl -s -m 60 $J $H/api/chat -d "$B" | head -c 200); echo "[A] $(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s $R") & (sleep 0.3; S=$(date +%s.%N); R=$(curl -s -m 60 $J $H/api/chat -d "$B" | head -c 200); echo "[B] $(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s $R") & wait
echo "===AFTER_PARALLEL sequential x1==="; S=$(date +%s.%N); R=$(curl -s -m 60 $J $H/api/chat -d "$B" | head -c 160); echo "$(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s $R"
echo "===HAILO_OLLAMA_JOURNAL==="; journalctl -u hailo-ollama.service -S -3m --no-pager -o short-iso | grep -viE "list_models" | tail -25
