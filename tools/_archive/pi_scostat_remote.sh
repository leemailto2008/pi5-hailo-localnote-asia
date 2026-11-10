cat > /tmp/scostat.py <<'PY'
import sys, struct, collections
VALID={0x08:0,0x38:1,0xC8:2,0xF8:3}
def load(path):
    f=open(path,'rb'); f.read(16); pk=[]
    while True:
        r=f.read(24)
        if len(r)<24: break
        olen,ilen,flags,drops,ts=struct.unpack('>IIIIq',r); d=f.read(ilen)
        if (flags&0xffff)==7 and len(d)>=4:
            h=struct.unpack('<H',d[0:2])[0]; pk.append((ts,(h>>12)&3,d[3:3+d[2]]))
    return pk
def crc_tab():
    t=[]
    for i in range(256):
        c=i
        for _ in range(8): c=((c<<1)^0x1D)&0xFF if c&0x80 else (c<<1)&0xFF
        t.append(c)
    return t
T=crc_tab()
def sbc_crc_ok(fr):  # fr starts at 0xAD
    if len(fr)<8: return None
    crc=0x0F
    for b in (fr[1],fr[2]): crc=T[crc^b]
    for b in fr[4:8]: crc=T[crc^b]   # mSBC mono/8 subbands: 32 bits scale factors
    return crc==fr[3]
for path in sys.argv[1:]:
    pk=load(path); print(f"== {path}: sco_rx={len(pk)}")
    if not pk: continue
    print("  pkt_status_flags:",dict(collections.Counter(p[1] for p in pk)))
    b1=collections.Counter(p[2][1] for p in pk if len(p[2])>1); print("  H2 byte1 histogram:", {f'0x{k:02X}':v for k,v in sorted(b1.items(), key=lambda x:-x[1])[:10]})
    b0=collections.Counter(p[2][0] for p in pk); b2=collections.Counter(p[2][2] for p in pk if len(p[2])>2)
    print("  byte0==0x01:", b0.get(1,0), " byte2==0xAD:", b2.get(0xAD,0))
    hdr_ok=[p for p in pk if p[2][0]==1 and p[2][1] in VALID and p[2][2]==0xAD]
    print(f"  valid H2+sync header: {len(hdr_ok)}/{len(pk)} ({len(hdr_ok)/len(pk)*100:.1f}%)")
    crc=collections.Counter(sbc_crc_ok(p[2][2:]) for p in hdr_ok); print("  SBC header CRC among valid-header frames:", dict(crc))
    allcrc=collections.Counter(sbc_crc_ok(p[2][2:]) for p in pk if len(p[2])>2 and p[2][2]==0xAD); print("  SBC CRC among frames with 0xAD syncword:", dict(allcrc))
    # sequence continuity among valid headers
    seqerr=0; last=None
    for p in hdr_ok:
        s=VALID[p[2][1]]
        if last is not None and s!=(last+1)%4: seqerr+=1
        last=s
    print("  seq discontinuities (valid frames):", seqerr)
    # bit-error analysis on header bytes: hamming distance of byte1 to nearest valid
    def hd(a,b): return bin(a^b).count('1')
    dist=collections.Counter(min(hd(p[2][1],v) for v in VALID) for p in pk if len(p[2])>1); print("  byte1 hamming distance to nearest valid:", dict(sorted(dist.items())))
    # burstiness: run-lengths of invalid packets
    inv=[not (p[2][0]==1 and p[2][1] in VALID and p[2][2]==0xAD) for p in pk]
    runs=[]; c=0
    for x in inv:
        if x: c+=1
        elif c: runs.append(c); c=0
    if c: runs.append(c)
    rc=collections.Counter(min(r,50) for r in runs); print("  invalid run-length histogram:", dict(sorted(rc.items())))
    # all-zero payloads?
    print("  all-zero payloads:", sum(1 for p in pk if all(b==0 for b in p[2])))
    # timeline per second
    t0=pk[0][0]; per=collections.defaultdict(lambda:[0,0])
    for p,bad in zip(pk,inv): k=int((p[0]-t0)/1e6); per[k][0]+=bad; per[k][1]+=1
    print("  invalid/total per second:", ' '.join(f"{per[k][0]}/{per[k][1]}" for k in sorted(per)))
PY
sudo -n cat /tmp/sn1.snoop > /tmp/sn1c.snoop; sudo -n cat /tmp/sn2.snoop > /tmp/sn2c.snoop; sudo -n cat /tmp/sco3.snoop > /tmp/sco3c.snoop 2>/dev/null
python3 /tmp/scostat.py /tmp/sn1c.snoop /tmp/sn2c.snoop /tmp/sco3c.snoop
