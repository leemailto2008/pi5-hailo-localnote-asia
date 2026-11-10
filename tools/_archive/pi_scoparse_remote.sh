cat > /tmp/btsnoop_sco.py <<'PY'
import sys, struct, collections
f=open(sys.argv[1],'rb'); hdr=f.read(16); assert hdr[:8]==b'btsnoop\0'; print("datalink:",struct.unpack(">I",hdr[12:16])[0])
pk=[]; 
while True:
    r=f.read(24)
    if len(r)<24: break
    olen,ilen,flags,drops,ts=struct.unpack('>IIIIq',r); data=f.read(ilen)
    if not data: break
    op=flags&0xffff
    if op==7 and len(data)>=3:  # btmon monitor opcode 7 = SCO RX (data = SCO header + payload)
        h=struct.unpack('<H',data[0:2])[0]; handle=h&0x0fff; pstat=(h>>12)&3; ln=data[2]; pk.append((ts,handle,pstat,data[3:3+ln]))
print("sco_rx_packets:",len(pk))
if not pk: sys.exit()
sizes=collections.Counter(len(p[3]) for p in pk); print("sizes:",dict(sizes))
pst=collections.Counter(p[2] for p in pk); print("packet_status_flags (0=ok,1=partial,2=nodata,3=lost):",dict(pst))
# mSBC H2 header: byte0=0x01, byte1 in {0x08,0x38,0xC8,0xF8}, byte2=0xAD (SBC syncword)
seq_map={0x08:0,0x38:1,0xC8:2,0xF8:3}
good=bad=0; badex=[]; seqerr=0; last=None; zeros=0
for ts,hd,ps,d in pk:
    if len(d)>=3 and d[0]==0x01 and d[1] in seq_map and d[2]==0xAD:
        good+=1; s=seq_map[d[1]]
        if last is not None and s!=(last+1)%4: seqerr+=1
        last=s
    else:
        bad+=1
        if all(b==0 for b in d): zeros+=1
        if len(badex)<6: badex.append(d[:8].hex(' '))
print(f"valid_msbc_frames:{good} invalid:{bad} (all-zero payload:{zeros}) seq_discontinuities:{seqerr}")
print("invalid examples (first 8 bytes):", badex)
# timeline: invalid per 0.5s bucket
t0=pk[0][0]; b=collections.Counter(); bt=collections.Counter()
for ts,hd,ps,d in pk:
    k=int((ts-t0)/500000); bt[k]+=1
    if not (len(d)>=3 and d[0]==0x01 and d[1] in seq_map and d[2]==0xAD): b[k]+=1
print("per-0.5s invalid/total:", ' '.join(f"{b[k]}/{bt[k]}" for k in sorted(bt)))
# SBC frame CRC check on valid frames: compute CRC-8 as per A2DP SBC spec over header fields
def sbc_crc_ok(frame):
    # frame starts at 0xAD; SBC header: syncword, byte1 (freq,blocks,mode,alloc), byte2 (subbands,bitpool), byte3 crc
    if len(frame)<4: return None
    crc_table=[0]*256
    for i in range(256):
        c=i
        for _ in range(8): c=((c<<1)^0x1D)&0xFF if c&0x80 else (c<<1)&0xFF
        crc_table[i]=c
    hb1=frame[1]; hb2=frame[2]
    crc=0x0F; crc=crc_table[crc^hb1]; crc=crc_table[crc^hb2]
    # mSBC: mono, 8 subbands, 15 blocks, bitpool 26 -> scale factors: 8 subbands * 4 bits = 32 bits = 4 bytes, join bits none (mono)
    sf=frame[4:8]
    for byte in sf: crc=crc_table[crc^byte]
    return crc==frame[3]
ok=fail=0
for ts,hd,ps,d in pk:
    if len(d)>=3 and d[0]==0x01 and d[1] in seq_map and d[2]==0xAD:
        r=sbc_crc_ok(d[2:])
        if r is True: ok+=1
        elif r is False: fail+=1
print(f"sbc_header_crc ok:{ok} fail:{fail}")
PY
echo "===PARSE sn1 (A, sniff allowed)==="; sudo -n cat /tmp/sn1.snoop > /tmp/sn1c.snoop; python3 /tmp/btsnoop_sco.py /tmp/sn1c.snoop
echo "===PARSE sn2 (B, sniff disabled)==="; sudo -n cat /tmp/sn2.snoop > /tmp/sn2c.snoop; python3 /tmp/btsnoop_sco.py /tmp/sn2c.snoop
echo "===RESTORE link policy==="; sudo -n hciconfig hci0 lp RSWITCH,SNIFF 2>&1; sudo -n hcitool lp A0:D1:2A:42:12:34 RSWITCH,SNIFF 2>&1 | tail -1
echo "===ERRONEOUS DATA REPORTING==="; sudo -n hcitool cmd 0x03 0x005A 2>/dev/null | tail -1
