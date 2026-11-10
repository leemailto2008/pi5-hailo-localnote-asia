cd /tmp && python3 - <<'PY'
import json, urllib.request
H="http://127.0.0.1:11435/api/chat"
def ask(content, label):
    body=json.dumps({"model":"qwen3:1.7b","messages":[{"role":"user","content":content}],"stream":False,"think":False,"options":{"num_predict":60,"temperature":0}}).encode()
    req=urllib.request.Request(H,data=body,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            print(f"[{label}] OK ->", json.loads(r.read())["message"]["content"][:150].replace("\n","⏎"))
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}:", e.read().decode()[:160].replace("\n"," | "))
ask("Repeat exactly the text between <<>> and tell me how many lines it has: <<alpha\nbeta\ngamma>>", "raw LF")
ask("Repeat exactly the text between <<>> and tell me how many lines it has: <<alpha\\nbeta\\ngamma>>", "literal backslash-n")
ask("Repeat exactly the text between <<>> and tell me how many lines it has: <<alpha beta gamma>>", "U+2028 line sep")
ask('Repeat exactly: He said "hello" to me.', "double quote")
ask('Repeat exactly: He said \\"hello\\" to me.', "escaped double quote")
ask("Repeat exactly: tab\there and back\\slash", "tab + backslash")
ask("Repeat exactly: 中文「引號」與『書名號』，以及：冒號。", "CJK punctuation")
PY
