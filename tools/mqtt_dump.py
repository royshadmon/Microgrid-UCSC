import socket, sys, time
def rlen(n):
    out=bytearray()
    while True:
        d=n%128; n//=128
        if n>0: d|=128
        out.append(d)
        if n==0: break
    return bytes(out)
def mkstr(s):
    b=s.encode(); return len(b).to_bytes(2,"big")+b
host=sys.argv[1]; port=int(sys.argv[2]); secs=int(sys.argv[3])
user=sys.argv[4] if len(sys.argv)>4 else None
pw=sys.argv[5] if len(sys.argv)>5 else None
topic=sys.argv[6] if len(sys.argv)>6 else "#"
s=socket.create_connection((host,port),timeout=10)
flags=2; payload=mkstr("iems-probe-"+str(int(time.time())))
if user is not None:
    flags|=0x80; payload+=mkstr(user)
    if pw is not None:
        flags|=0x40; payload+=mkstr(pw)
vh=mkstr("MQTT")+bytes([4,flags])+(60).to_bytes(2,"big")
pkt=vh+payload
s.sendall(bytes([0x10])+rlen(len(pkt))+pkt)
def rb():
    b=s.recv(1)
    if not b: raise EOFError
    return b[0]
def rl():
    m,v=1,0
    while True:
        d=rb(); v+=(d&127)*m
        if not(d&128): return v
        m*=128
def rn(n):
    buf=b""
    while len(buf)<n:
        c=s.recv(n-len(buf))
        if not c: raise EOFError
        buf+=c
    return buf
h=rb(); ln=rl(); body=rn(ln)
rc=body[1]
print("CONNACK rc="+str(rc)+(" ACCEPTED" if rc==0 else " REJECTED"))
if rc!=0: sys.exit(1)
sub=(1).to_bytes(2,"big")+mkstr(topic)+bytes([0])
s.sendall(bytes([0x82])+rlen(len(sub))+sub)
seen={}; cnt={}; dl=time.time()+secs; s.settimeout(5)
while time.time()<dl:
    try:
        h=rb(); ln=rl(); body=rn(ln)
    except (socket.timeout,EOFError): continue
    if h>>4!=3: continue
    tl=int.from_bytes(body[0:2],"big"); t=body[2:2+tl].decode("utf-8","replace")
    off=2+tl
    if (h>>1)&3: off+=2
    v=body[off:].decode("utf-8","replace")
    seen[t]=v; cnt[t]=cnt.get(t,0)+1
s.close()
print("TOPICS="+str(len(seen))+" over "+str(secs)+"s")
for t in sorted(seen):
    print(str(cnt[t]).rjust(4)+"x  "+t+"  =  "+seen[t][:140])
