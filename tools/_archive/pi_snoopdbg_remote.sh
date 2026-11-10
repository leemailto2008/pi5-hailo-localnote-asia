python3 - <<'PY'
import struct, collections
f=open('/tmp/sn1c.snoop','rb'); hdr=f.read(16); print(hdr)
ops=collections.Counter(); samples={}
n=0
while True:
    r=f.read(24)
    if len(r)<24: break
    olen,ilen,flags,drops,ts=struct.unpack('>IIIIq',r); data=f.read(ilen); n+=1
    ops[flags]+=1
    if flags not in samples: samples[flags]=(olen,ilen,data[:12].hex(' '))
print("records:",n); 
for k,v in ops.most_common(12): print(f"flags=0x{k:08x} count={v} sample(olen,ilen,bytes)={samples[k]}")
PY
