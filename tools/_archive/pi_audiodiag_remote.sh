echo "===LATEST_REC==="; ls -lt /dev/shm/audio_cache/*.ogg 2>/dev/null | head -5
F=$(ls -t /dev/shm/audio_cache/m_*.ogg 2>/dev/null | head -1); echo "file=$F"; cp -f "$F" /tmp/latest_rec.ogg
echo "===FFPROBE==="; ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bit_rate:format=duration -of default=nw=1 "$F"
echo "===ASTATS==="; ffmpeg -v info -i "$F" -af "astats=measure_overall=Peak_level+RMS_level+RMS_peak+RMS_trough+Flat_factor+Peak_count+Noise_floor+Dynamic_range:measure_perchannel=none,volumedetect" -f null - 2>&1 | grep -E "Peak level|RMS level|RMS peak|RMS trough|Flat factor|Peak count|Noise floor|Dynamic range|mean_volume|max_volume|histogram" | head -20
echo "===BT_DEVICE_PROFILE_CODEC==="; pw-dump 2>/dev/null | python3 -c "
import sys,json
nodes=json.load(sys.stdin)
for n in nodes:
    p=n.get('info',{}).get('props',{}) or {}
    t=n.get('type','')
    if p.get('device.api')=='bluez5' and t.endswith('Device'):
        params=n.get('info',{}).get('params',{})
        print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in params.get('Profile',[])],'enum=',[x.get('name') for x in params.get('EnumProfile',[])])
        for pr in params.get('Props',[]): 
            for k in ('bluez5.codec','api.bluez5.codec'):
                if k in pr: print('  codec prop',k,pr[k])
    if 'bluez' in p.get('node.name','') and t.endswith('Node'):
        print('NODE',n['id'],p.get('node.name'),p.get('media.class'),'codec=',p.get('api.bluez5.codec'),'rate=',p.get('audio.rate'),'ch=',p.get('audio.channels'),'profile=',p.get('api.bluez5.profile'),'transport=',p.get('api.bluez5.transport'))
"
echo "===WPCTL_DEFAULT_SOURCE==="; wpctl status 2>/dev/null | sed -n '/Sources:/,/Filters:/p' | head -8
echo "===SCO_ERRORS_LAST_HOUR==="; journalctl -S -60m --no-pager -o short-iso 2>/dev/null | grep -iE "sco|decode failed|msbc|cvsd|bluez5" | grep -v "list_models" | tail -25
echo "===USER_JOURNAL_PIPEWIRE==="; journalctl --user -S -60m --no-pager -o short-iso 2>/dev/null | grep -iE "sco|decode|bluez|msbc|cvsd|xrun|underrun" | tail -20
echo "===BT_INFO==="; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Name|Connected|UUID: (Handsfree|Headset|Audio)"
echo "===HCI_FEATURES==="; btmgmt info 2>/dev/null | grep -iE "supported settings|current settings|wide|esco" ; hciconfig -a 2>/dev/null | grep -iE "Features|Packet|SCO|eSCO|Link policy" | head -6
echo "===BLUEZ_MAIN_CONF==="; grep -vE "^\s*#|^\s*$" /etc/bluetooth/main.conf; echo "---"; grep -rhoE "bluez5\.(enable-msbc|codecs|hfphsp-backend|roles|msbc-force-mtu|enable-sbc-xq|headset-roles)[^,}]*" /etc/wireplumber /usr/share/wireplumber ~/.config/wireplumber 2>/dev/null | sort -u
echo "===LAST_RECORD_JOURNAL==="; journalctl -u pi5-dispatcher-api.service -S -60m --no-pager -o short-iso | grep -iE "鎖定|profile|mSBC|source|VoicePipeline\] .*(錄音|record|ffmpeg)|首切片|decode" | tail -15
