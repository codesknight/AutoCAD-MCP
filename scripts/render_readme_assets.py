"""Generate original README artwork. The GIF illustrates tools; it is not a recording."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets"
PREVIEW = ROOT / ".git/readme-preview"
W, H, S = 1080, 590, 2
BG, PANEL = "#091321", "#101e30"
WHITE, MUTED, BLUE, GOLD, GREEN = "#edf4ff", "#9aacc6", "#72caff", "#ffc578", "#67dfb0"


def font(size, bold=False, mono=False):
    path = Path("C:/Windows/Fonts") / ("consola.ttf" if mono else "segoeuib.ttf" if bold else "segoeui.ttf")
    if path.exists():
        return ImageFont.truetype(str(path), size*S)
    return ImageFont.truetype("DejaVuSansMono.ttf" if mono else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size*S)


def box(d, xy, fill, outline=None, radius=12):
    d.rounded_rectangle(tuple(round(v*S) for v in xy),radius=radius*S,fill=fill,outline=outline,width=S)


def text(d, xy, value, size=16, fill=WHITE, bold=False, mono=False):
    d.text(tuple(round(v*S) for v in xy),value,font=font(size,bold,mono),fill=fill)


def line(d, points, fill, width=2):
    d.line([(round(x*S),round(y*S)) for x,y in points],fill=fill,width=width*S,joint="curve")


def dot(d, point, fill, r=3):
    x,y=point
    d.ellipse(((x-r)*S,(y-r)*S,(x+r)*S,(y+r)*S),fill=fill)


def frame(stage, progress):
    im=Image.new("RGB",(W*S,H*S),BG)
    d=ImageDraw.Draw(im)
    text(d,(36,23),"AUTOCAD MCP  /  ILLUSTRATED WORKFLOW",13,BLUE,bold=True)
    text(d,(34,53),"From prompt to verified geometry",32,bold=True)
    text(d,(36,101),"MCP client  >  Python tool server  >  AutoCAD backend",16,MUTED)
    box(d,(36,146,321,505),PANEL,"#263b52")
    box(d,(344,146,1044,505),"#0c1827","#263b52")
    text(d,(57,162),"STRUCTURED TOOL CALLS",11,MUTED,bold=True)
    text(d,(365,162),"MODEL SPACE",11,MUTED,bold=True)
    text(d,(913,162),"WCS / XY",11,BLUE,mono=True)
    line(d,[(345,190),(1043,190)],"#24384c",1)
    steps=[
        ("new_drawing","Create a blank scratch drawing"),
        ("draw_line","(0, 0, 0)  >  (10, 0, 0)"),
        ("draw_circle","C (20, 0, 0)  /  radius 5"),
        ("query_entities","Read back geometry and count"),
    ]
    for i,(name,detail) in enumerate(steps):
        y=211+i*69
        if i==stage: box(d,(48,y-8,309,y+47),"#18334a","#315675",8)
        color=GREEN if i<stage else BLUE if i==stage else "#536b85"
        dot(d,(65,y+8),color,4)
        text(d,(81,y-2),name,17,color,bold=True,mono=True)
        text(d,(81,y+24),detail,11,MUTED)
    for x in range(374,1035,30): line(d,[(x,201),(x,492)],"#15273a",1)
    for y in range(221,500,30): line(d,[(355,y),(1032,y)],"#15273a",1)
    a,b,c,r=(440,337),(620,337),(800,337),90
    if stage==0:
        text(d,(552,312),"Blank model space",23,"#66839d",bold=True)
        text(d,(576,349),"Ready for tool calls",14,MUTED)
    if stage>=1:
        t=progress if stage==1 else 1
        p=(a[0]+(b[0]-a[0])*t,a[1])
        line(d,[a,p],BLUE,3)
        dot(d,a,BLUE,4);dot(d,p,BLUE,4)
        text(d,(425,359),"(0, 0)",12,MUTED,mono=True)
        if t>.95: text(d,(594,359),"(10, 0)",12,MUTED,mono=True)
        if stage==1:
            line(d,[(p[0]-8,p[1]-8),(p[0]+8,p[1]+8)],WHITE,1)
            line(d,[(p[0]-8,p[1]+8),(p[0]+8,p[1]-8)],WHITE,1)
    if stage>=2:
        t=progress if stage==2 else 1
        d.arc(((c[0]-r)*S,(c[1]-r)*S,(c[0]+r)*S,(c[1]+r)*S),
              start=-90,end=-90+360*max(.001,t),fill=GOLD,width=3*S)
        dot(d,c,GOLD)
        line(d,[(790,337),(810,337)],"#9b825e",1)
        line(d,[(800,327),(800,347)],"#9b825e",1)
        text(d,(762,439),"C (20, 0)",12,MUTED,mono=True)
        text(d,(856,258),"r = 5",13,GOLD,mono=True)
    if stage==3:
        box(d,(428,324,632,350),None,"#365e58",3)
        box(d,(700,237,900,437),None,"#365e58",4)
        box(d,(718,201,1019,231),"#15372f","#2a6655",7)
        text(d,(734,206),"2 entities / geometry verified",13,GREEN,bold=True)
    line(d,[(381,476),(410,476)],BLUE,2)
    line(d,[(381,476),(381,447)],GREEN,2)
    text(d,(416,467),"X",11,BLUE);text(d,(376,431),"Y",11,GREEN)
    labels=["CREATE A SAFE WORKSPACE","DRAW A LINE","DRAW A CIRCLE","VERIFY THE RESULT"]
    text(d,(36,523),f"0{stage+1}  {labels[stage]}",13,GREEN if stage==3 else BLUE,bold=True)
    text(d,(36,553),"Synthetic fixture illustration - not a live AutoCAD screen recording.",13,MUTED)
    return im.resize((W,H),Image.Resampling.LANCZOS)


def cover():
    grid="".join(f'<path d="M{x} 0V340"/>' for x in range(0,1201,32))
    grid+="".join(f'<path d="M0 {y}H1200"/>' for y in range(0,341,32))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="340" viewBox="0 0 1200 340" role="img" aria-labelledby="title desc">
<title id="title">AutoCAD MCP — Natural language. Real CAD.</title>
<desc id="desc">Original blueprint project cover. COM is the default backend; HTTP Bridge is experimental.</desc>
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#071321"/><stop offset="1" stop-color="#12263b"/></linearGradient>
<radialGradient id="halo"><stop stop-color="#214d6d" stop-opacity=".65"/><stop offset="1" stop-color="#102033" stop-opacity="0"/></radialGradient></defs>
<rect width="1200" height="340" rx="18" fill="url(#bg)"/>
<g stroke="#6eb8dc" stroke-opacity=".065" stroke-width="1">{grid}</g>
<ellipse cx="950" cy="165" rx="295" ry="190" fill="url(#halo)"/>
<g font-family="Segoe UI,Arial,sans-serif">
<text x="58" y="64" fill="#76ceff" font-size="13" font-weight="700" letter-spacing="2">MODEL CONTEXT PROTOCOL × CAD</text>
<text x="54" y="143" fill="#f2f7ff" font-size="61" font-weight="750" letter-spacing="-2">AutoCAD MCP</text>
<text x="58" y="190" fill="#c1cede" font-size="26">Natural language. Real CAD.</text>
<text x="58" y="225" fill="#8da5bf" font-size="15">Draw · inspect · edit · verify</text>
<rect x="58" y="256" width="147" height="31" rx="15" fill="#15364b" stroke="#2e607a"/>
<circle cx="76" cy="271.5" r="4" fill="#76ceff"/>
<text x="88" y="277" fill="#caeaff" font-size="12" font-weight="600">COM / DEFAULT</text>
<rect x="217" y="256" width="236" height="31" rx="15" fill="#302b27" stroke="#65513a"/>
<circle cx="235" cy="271.5" r="4" fill="#ffca81"/>
<text x="247" y="277" fill="#ffe1b5" font-size="12" font-weight="600">.NET HTTP / EXPERIMENTAL</text></g>
<rect x="650" y="42" width="503" height="253" rx="13" fill="#0b1a2a" fill-opacity=".7" stroke="#34516b"/>
<g fill="#7d9cb6" font-family="Consolas,monospace" font-size="10" letter-spacing="1"><text x="672" y="65">GEOMETRY / LAYERS / QUERIES</text><text x="1088" y="65">WCS</text></g>
<path d="M650 80H1153" stroke="#29445d"/>
<g fill="none" stroke="#73cfff" stroke-width="2.5" stroke-linecap="round"><path d="M695 137H801V207H903"/>
<circle cx="971" cy="172" r="67"/><circle cx="971" cy="172" r="36" stroke-opacity=".45"/></g>
<g stroke="#ffca81" fill="none" stroke-width="1.3"><path d="M971 91V253M890 172H1052" stroke-dasharray="5 6" stroke-opacity=".65"/>
<path d="M695 255H801M695 248V262M801 248V262"/></g>
<g fill="#73cfff"><circle cx="695" cy="137" r="4"/><circle cx="801" cy="137" r="4"/><circle cx="801" cy="207" r="4"/></g>
<circle cx="971" cy="172" r="4" fill="#ffca81"/>
<g font-family="Consolas,monospace" font-size="11" fill="#8ba7be"><text x="716" y="276">STRUCTURED TOOLS</text><text x="1057" y="211">r</text></g></svg>'''


def main():
    ASSETS.mkdir(parents=True,exist_ok=True);PREVIEW.mkdir(parents=True,exist_ok=True)
    (ASSETS/"cover.svg").write_text(cover(),encoding="utf-8")
    reps=[frame(stage,1) for stage in range(4)]
    sheet=Image.new("RGB",(W*2,H*2),BG)
    for i,im in enumerate(reps): sheet.paste(im,((i%2)*W,(i//2)*H))
    sheet.resize((1296,708),Image.Resampling.LANCZOS).save(PREVIEW/"workflow-contact-sheet.png")
    palette=sheet.quantize(colors=128)
    frames,durations=[],[]
    for stage,hold in enumerate([6,8,8,25]):
        for i in range(12):
            frames.append(frame(stage,1-(1-i/11)**3).quantize(palette=palette,dither=Image.Dither.NONE))
            durations.append(90)
        frames.append(reps[stage].quantize(palette=palette,dither=Image.Dither.NONE))
        durations.append(hold*90)
    frames[0].save(ASSETS/"workflow.gif",save_all=True,append_images=frames[1:],
                   duration=durations,loop=0,optimize=True,disposal=2)
    reps[-1].save(PREVIEW/"workflow-final.png")
    print(f"Generated cover.svg and workflow.gif ({(ASSETS/'workflow.gif').stat().st_size:,} bytes)")


if __name__=="__main__":
    main()
