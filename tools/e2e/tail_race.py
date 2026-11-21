#!/usr/bin/env python3
"""上一場紀要一出來就立刻開下一場，檢查上一場即時翻譯有沒有翻完（6b2abe3 的回歸測試；11-21 W18 實機 PASS）。
用法（Pi 上、e2e 已在跑某一場、即時翻譯開著）：python3 tail_race.py <job_A>
注意：下一場會蓋掉 /api/result，所以同時跑的 run_suite 那場評分會失敗，只看這裡印的 RACE。
做法：每 0.3 s 看 /api/status；job_A 變 done 的瞬間記下翻好段數、POST /api/record 60 s（bypass_summary），
200 s 後讀 job_A 的 live_tr.json，印出 done/segments。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1"


def api(path, body=None, t=10):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=t).read())


def main():
    job_a = sys.argv[1]
    while True:
        try:
            st = api("/api/status", t=3)
        except OSError as e:
            print("status err", e)
            time.sleep(1)
            continue
        if st.get("job") == job_a and st.get("state") == "done":
            m = st.get("metrics") or {}
            print("A done at", time.strftime("%T"), "tr", m.get("live_tr_done"), "/", m.get("live_tr_segments"), flush=True)
            break
        time.sleep(0.3)
    b = api("/api/record", {"seconds": 60, "bypass_summary": True}).get("job")
    print("B started", b, time.strftime("%T"), flush=True)
    time.sleep(200)
    t = json.load(open(f"/dev/shm/localnote_state/{job_a}.live_tr.json"))
    print("A final", t["live_tr_done"], "/", len(t["segments"]), "kept", t["live_tr_kept"], flush=True)
    print("RACE", "PASS" if t["live_tr_done"] == len(t["segments"]) else "FAIL", flush=True)


if __name__ == "__main__":
    main()
