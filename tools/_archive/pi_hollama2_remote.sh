H=http://127.0.0.1:11435; J='-H Content-Type:application/json'
echo "===test_hailo_qwen3.py==="; cat /home/pi/test_hailo_qwen3.py
echo "===aria2_qwen3.log tail==="; tail -3 /home/pi/aria2_qwen3.log
probe(){ echo "--- $1"; curl -s -m 60 $J $H/api/generate -d "$2" | head -c 400; echo; }
probe "minimal" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false}'
probe "+num_predict" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false,"options":{"num_predict":20}}'
probe "+temperature" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false,"options":{"num_predict":20,"temperature":0.2}}'
probe "+keep_alive str" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false,"keep_alive":"24h"}'
probe "+keep_alive int" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false,"keep_alive":86400}'
probe "+think false" '{"model":"qwen3:1.7b","prompt":"Say hi in English only.","stream":false,"think":false}'
probe "+system" '{"model":"qwen3:1.7b","system":"Output English only.","prompt":"今天天氣很好。","stream":false,"think":false,"options":{"num_predict":30}}'
echo "--- stream minimal"; curl -s -N -m 60 $J $H/api/generate -d '{"model":"qwen3:1.7b","prompt":"Count from one to five in English words.","stream":true,"think":false,"options":{"num_predict":30}}' > /tmp/hs.txt; head -4 /tmp/hs.txt; echo ...; tail -1 /tmp/hs.txt; echo "lines: $(wc -l < /tmp/hs.txt)"
echo "--- chat stream"; curl -s -N -m 60 $J $H/api/chat -d '{"model":"qwen3:1.7b","messages":[{"role":"user","content":"Count from one to five in English words."}],"stream":true,"think":false,"options":{"num_predict":30}}' > /tmp/hc.txt; head -3 /tmp/hc.txt; echo ...; tail -1 /tmp/hc.txt; echo "lines: $(wc -l < /tmp/hc.txt)"
echo "--- chat TTFT/TPS (zh->en translate, ~40 tok)"; S=$(date +%s.%N); curl -s -N -m 60 $J $H/api/chat -d '{"model":"qwen3:1.7b","messages":[{"role":"system","content":"你是即時口譯員。把使用者的中文翻成自然的英文，只輸出英文。"},{"role":"user","content":"我們今天討論了三件事：第一是藍牙耳機的配對問題已經修好了，第二是語音辨識現在跑在 NPU 上，第三是下週要把大語言模型也搬到 NPU。"}],"stream":true,"think":false,"options":{"temperature":0.2,"num_predict":120}}' | python3 -c "
import sys,json,time
t0=time.time(); first=None; n=0; txt=''
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    d=json.loads(line); c=d.get('message',{}).get('content','')
    if c and first is None: first=time.time()-t0
    n+=1; txt+=c
    if d.get('done'): tot=d.get('total_duration',0)/1e9; ev=d.get('eval_count'); evd=d.get('eval_duration',0)/1e9
print(f'TTFT={first:.2f}s chunks={n} wall={time.time()-t0:.2f}s total_duration={tot:.2f}s eval_count={ev} eval_duration={evd:.2f}s tps={(ev/evd) if ev and evd else 0:.1f}'); print('TEXT:',txt)"
echo "--- thinking default (no think flag) chat"; curl -s -m 60 $J $H/api/chat -d '{"model":"qwen3:1.7b","messages":[{"role":"user","content":"今天天氣很好。翻成英文。"}],"stream":false,"options":{"num_predict":60}}' | head -c 500; echo
