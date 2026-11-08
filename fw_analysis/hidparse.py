import sys
PAGES={0x01:"GenericDesktop",0x02:"Simulation",0x09:"Button",0x0F:"PID",0x06:"Generic",0xFF00:"Vendor"}
USAGES={(1,0x04):"Joystick",(1,0x05):"Gamepad",(1,0x30):"X",(1,0x31):"Y",(1,0x32):"Z",(1,0x33):"Rx",(1,0x34):"Ry",(1,0x35):"Rz",(1,0x36):"Slider",(1,0x39):"Hat",(1,1):"Pointer"}
def parse(b,start,limit=4000):
    i=start; depth=0; page=0; rid=0; size=0; count=0; out=[]; lmin=lmax=0; reports={}
    while i<min(len(b),start+limit):
        t=b[i]; sz={0:0,1:1,2:2,3:4}[t&3]; typ=(t>>2)&3; tag=t>>4
        raw=int.from_bytes(b[i+1:i+1+sz],"little") if sz else 0
        val=int.from_bytes(b[i+1:i+1+sz],"little",signed=True) if sz else 0
        ind="  "*depth
        if typ==1:
            if tag==0: page=raw; out.append(f"{ind}UsagePage {PAGES.get(raw,hex(raw))}")
            elif tag==1: lmin=val
            elif tag==2: lmax=val
            elif tag==7: size=raw
            elif tag==8: rid=raw; out.append(f"{ind}ReportID {raw}")
            elif tag==9: count=raw
        elif typ==2 and tag==0:
            nm=USAGES.get((page,raw)) if page==1 else None
            out.append(f"{ind}Usage {nm or hex(raw)}")
        elif typ==0:
            if tag==0xA: out.append(f"{ind}Collection {raw:#x}"); depth+=1
            elif tag==0xC:
                depth-=1; out.append("  "*max(depth,0)+"End")
                if depth<=0: i+=1+sz; break
            elif tag in(8,9,0xB):
                kind={8:"Input",9:"Output",0xB:"Feature"}[tag]
                out.append(f"{ind}{kind}({raw:#x}) size={size} count={count} range=[{lmin}..{lmax}]")
                reports[(kind,rid)]=reports.get((kind,rid),0)+size*count
        i+=1+sz
    return out,reports,i-start
