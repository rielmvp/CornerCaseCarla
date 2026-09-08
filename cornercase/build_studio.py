"""Build the two-page live demo into outputs/site.

  outputs/site/live.html    showcase: the reel (cornercase_1/4/2), pre-rendered
  outputs/site/studio.html  Live Studio: pick a corner case, model and car, then
                            Generate runs Alpamayo live on the GPU

  python cornercase/build_studio.py

The two are deliberately separate: the showcase is what you put on the projector,
the studio is the window you drive the live run from. The studio needs nothing
pre-rendered - every scenario listed here is run live when Generate is pressed.
The showcase needs outputs/site/reel/reel.mp4 (cornercase/build_reel.py).
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

GAL = paths.SITE
os.makedirs(GAL, exist_ok=True)

# The corner cases the studio offers, shown to visitors as cornercase_1..N in
# this order. Each stages a hazard that crashed both Alpamayo versions when the
# set was run (scenarios/curated/RESULTS.md).
CORNER = [
    "curated_08",   # pedestrian crossing against the signal, at night
    "curated_01",   # wrong-way car head-on
    "curated_05",   # pedestrian emerging between stopped cars, wet night
    "curated_09",   # construction barriers blocking the lane
    "curated_10",   # pedestrian stepping out from behind a van
]

# 1.5 first, so it is the dropdown default.
MODELS = [("v15", "Alpamayo 1.5", "1.5"), ("r1", "Alpamayo 1 (R1)", "1")]
# Ego vehicles offered in the studio; ids must match VEHICLES in live_worker.py.
# Every run is live, so the car matters: the cameras sit at the same offsets on
# each body, but the model sees a slightly different hood and the controller
# drives a different mass. Results differ by car, as they would on the road.
VEHICLES = [("mkz2017", "Lincoln MKZ 2017"), ("mkz2020", "Lincoln MKZ 2020"),
            ("charger", "Dodge Charger 2020"), ("model3", "Tesla Model 3")]
VIEWS  = [("bev", "Bird's-eye"), ("fpv", "First-person"), ("tpv", "Third-person")]
# One compiled video, built by cornercase/build_reel.py. Three separate <video>
# tags drift apart the moment one of them stalls; a single file cannot.
REEL_SRC = "reel/reel.mp4"
SEED, STEPS = 42, 100        # the scene the curated cases were checked at; 10 s of driving


def reel_columns():
    """Label column widths, taken from what build_reel.py actually rendered."""
    f = os.path.join(GAL, "reel", "reel.json")
    try:
        w = json.load(open(f))["widths"]
        return " ".join(f"{n}fr" for n in w)
    except Exception:
        return "repeat(3,1fr)"


DESC_RE = re.compile(r'^\s*description\s*=\s*"(.*)"\s*$', re.M)
TOWN_RE = re.compile(r"param\s+carla_map\s*=\s*['\"](Town\w+)['\"]")


def scenario_info(sid):
    """Caption and town straight from the scenario file."""
    text = open(paths.scenario_file(sid), encoding="utf-8").read()
    m, tm = DESC_RE.search(text), TOWN_RE.search(text)
    return (m.group(1).strip() if m else ""), (tm.group(1) if tm else "")


data = []
for n, sid in enumerate(CORNER, 1):
    if not os.path.exists(paths.scenario_file(sid)):
        print(f"  ! {sid}: no scenario file - skipped")
        continue
    cap, town = scenario_info(sid)
    data.append({"id": sid, "name": f"cornercase_{n}", "caption": cap, "cc": True,
                 "nc": False,
                 "models": {tag: {"label": label, "version": ver, "town": town,
                                  "seed": SEED, "frames": STEPS}
                            for tag, label, ver in MODELS}})

CSS = r"""
:root{--bg:#0f1115;--panel:#171a21;--card:#12161d;--line:#252a34;--fg:#e6e9ef;
--dim:#9aa3b2;--acc:#5aa9ff;--ok:#5fcf80;--warn:#e0b341;--err:#ff8b8b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:var(--acc)}
.top{display:flex;align-items:center;gap:14px;padding:13px 26px;
background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.top h1{margin:0;font-size:15px;letter-spacing:.2px}
.top .sub{color:var(--dim);font-size:11.5px}
.spacer{flex:1}
.page{max-width:1220px;margin:0 auto;padding:22px 26px 60px}
.cap{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--acc);
border-radius:0 10px 10px 0;padding:14px 18px;margin-bottom:14px}
.cap .lbl{color:var(--dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px}
.cap .txt{font-size:14.5px;line-height:1.6}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.b{background:#1e222b;border:1px solid var(--line);color:var(--dim);
border-radius:999px;padding:3px 10px;font-size:11px;white-space:nowrap}
.models{display:flex;gap:9px;margin:14px 0}
.mbtn{background:#1a1e27;border:1.5px solid var(--line);color:var(--dim);border-radius:8px;
padding:9px 18px;font-size:13px;font-weight:600;cursor:pointer}
.mbtn.on{background:#1d3a5f;border-color:var(--acc);color:#fff;box-shadow:0 0 0 3px rgba(90,169,255,.15)}
.mbtn:disabled{opacity:.35;cursor:not-allowed}
.cot{background:#141a13;border-left:3px solid #4a7c3f;padding:10px 14px;
border-radius:0 8px 8px 0;margin:14px 0;color:#cfe3c8;font-size:13px}
.cot b{color:#8fd47f}
.view h3{margin:0 0 5px;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
video{width:100%;border-radius:9px;background:#000;border:1px solid var(--line);display:block}
.btn{background:#1a1e27;border:1.5px solid var(--line);color:var(--fg);border-radius:8px;
padding:8px 15px;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{border-color:var(--acc)}
.btn.go{background:#1f6f3f;border-color:#2e9e5b;color:#fff}
.btn.go:disabled{opacity:.4;cursor:not-allowed}
.dot{font-size:11.5px;white-space:nowrap}
select,input{background:#0f1218;color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:7px 9px;font-size:12.5px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin:16px 0}
@media(max-width:1250px){.row3{grid-template-columns:1fr}}
.wrap{display:flex;height:100vh}
aside{width:290px;flex:0 0 290px;background:var(--panel);border-right:1px solid var(--line);
display:flex;flex-direction:column}
aside header{padding:15px 16px;border-bottom:1px solid var(--line)}
aside h1{margin:0;font-size:15px}
.controls{padding:10px 14px;border-bottom:1px solid var(--line)}
.controls select{width:100%}
ul{list-style:none;margin:0;padding:6px;overflow-y:auto;flex:1}
li{padding:8px 11px;border-radius:6px;cursor:pointer;display:flex;gap:8px;align-items:center}
li:hover{background:#1e222b}
li.sel{background:#23324a;box-shadow:inset 2px 0 0 var(--acc)}
.nm{font-weight:600;font-size:12.5px}.tw{color:var(--dim);font-size:10.5px;margin-left:auto}
/* corner cases amber, normal cases green, in both the list and the panel */
.nm.cc,h2.cc{color:var(--warn)}
.nm.nc,h2.nc{color:var(--ok)}
.foot{padding:12px 14px;border-top:1px solid var(--line);margin-top:auto}
.foot .btn{width:100%;text-align:center}
.stat{padding:11px 15px;border-bottom:1px solid var(--line);font-size:11.5px}
main{flex:1;overflow-y:auto;padding:20px 26px 50px;min-width:0}
.note{margin-top:22px;padding:12px 15px;border-left:3px solid #6b5b1f;background:#1c1a12;
color:#cfc39a;font-size:12px;border-radius:0 8px 8px 0}
/* Shell shared by both pages: title bar, body, full-width action bar. */
.shell{display:flex;flex-direction:column;height:100vh}
.appbar{flex:0 0 auto;padding:15px 26px;background:var(--panel);
border-bottom:1px solid var(--line)}
.appbar h1{margin:0;font-size:16px;font-weight:650;letter-spacing:.2px}
/* The showcase is projected, so its title is set larger and centred; the
   studio keeps the compact bar because its sidebar needs the height. */
.appbar.big{padding:18px 26px}
.appbar.big h1{font-size:26px;font-weight:700;text-align:center;letter-spacing:.3px}
.shell .wrap{flex:1;min-height:0;height:auto}
.fullmain{flex:1;min-height:0;overflow-y:auto;padding:20px 26px 26px}
.bottombar{flex:0 0 auto;display:block;width:100%;text-align:center;
padding:16px 0;font-size:14.5px;font-weight:700;letter-spacing:.3px;
text-decoration:none;background:#1f6f3f;color:#fff;border-top:1px solid #2e9e5b}
.bottombar:hover{background:#248049}
.bottombar.back{background:#1a1e27;color:var(--fg);border-top:1px solid var(--line)}
.bottombar.back:hover{background:#232833;color:var(--acc)}
/* Reel: the three views are one video, so they cannot drift apart. Panel
   labels are drawn here rather than burned into the frames. */
/* The reel fills the band between the title bar and the action bar. At
   2880x540 it is width-limited on any normal screen; the max-height keeps it
   inside the band on tall or narrow windows instead of pushing the bar off. */
.fullmain.reelmain{display:flex;flex-direction:column;justify-content:center;
padding:12px 14px}
.reel{width:100%;margin:0 auto;min-height:0}
.reel video{width:100%;height:auto;display:block;border-radius:8px;
max-height:calc(100vh - 172px);object-fit:contain}
/* Columns track the real panel widths, which are unequal once the side views
   are cropped, so each label stays over its own panel. */
.plabels{display:grid;grid-template-columns:__PLCOLS__;margin-bottom:8px}
.plabels span{text-align:center;font-size:15px;font-weight:600;color:#aab3c2;
text-transform:uppercase;letter-spacing:.8px}
"""

SHOWCASE_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VLAs on Simulated Corner Cases</title><style>__CSS__
body{height:100vh;overflow:hidden}
</style></head><body><div class="shell">
<div class="appbar big"><h1>VLAs on Simulated Corner Cases</h1></div>
<main class="fullmain reelmain">
  <div class="reel">
    <div class="plabels"><span>Bird&rsquo;s-eye</span><span>First-person</span><span>Third-person</span></div>
    <video src="__REEL__" autoplay loop muted playsinline controls></video>
  </div>
</main>
<a class="bottombar" href="studio.html">&#9889; Generate scenarios</a>
</div></body></html>"""

STUDIO_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VLAs on Simulated Corner Cases</title><style>__CSS__
body{height:100vh;overflow:hidden}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:14px}
.card h2{margin:0 0 3px;font-size:15px}
.card .txt{color:#d6dbe4;font-size:13.5px;margin:8px 0 12px;
border-left:3px solid var(--acc);padding-left:12px}
.runbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.fld{display:flex;align-items:center;gap:6px;color:var(--dim);font-size:12px}
.prog{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:14px}
.bar{height:8px;background:#0b0e13;border-radius:4px;overflow:hidden;margin:11px 0}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,#3d7fd6,#5aa9ff);width:0;transition:width .4s}
.phase{font-weight:600;font-size:13.5px}
.muted{color:var(--dim);font-size:12px}
.spin{display:inline-block;width:13px;height:13px;border:2px solid #35507a;border-top-color:var(--acc);
border-radius:50%;animation:s .8s linear infinite;vertical-align:-2px;margin-right:8px}
@keyframes s{to{transform:rotate(360deg)}}
.err{color:var(--err)}
.buf{background:linear-gradient(90deg,#12161d,#161d29,#12161d);background-size:200% 100%;
animation:sh 2.6s ease-in-out infinite}
@keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
.stmt{font-size:13px;color:#cfe0f5;margin-top:9px}
.sub2{color:var(--dim);font-size:11.5px;margin-top:5px}
.dots::after{content:'';animation:d 1.4s steps(4,end) infinite}
@keyframes d{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
</style></head><body><div class="shell">
<div class="appbar"><h1>VLAs on Simulated Corner Cases</h1></div>
<div class="wrap">
<aside>
  <header><h1>&#9889; Live Studio</h1>
    <div class="sub">run Alpamayo live on the GPU</div></header>
  <div class="stat" id="hstat">checking worker&hellip;</div>
  <ul id="list"></ul>
</aside>
<main>
  <div id="cards"></div>
  <div id="prog"></div>
  <div id="out"></div>
</main></div>
<a class="bottombar back" href="live.html">&#8592; Back to showcase</a>
<script>
const DATA=__DATA__, MODELS=__MODELS__, VIEWS=__VIEWS__, VEHICLES=__VEHICLES__;
const list=document.getElementById('list');
let poll=null, ready=false, cur=(DATA[0]||{}).id, shown=null;
const SK='alpamayo_live_job';
function remember(j){try{j?sessionStorage.setItem(SK,j):sessionStorage.removeItem(SK)}catch(e){}}
function remembered(){try{return sessionStorage.getItem(SK)}catch(e){return null}}

function renderList(){
  list.innerHTML='';
  DATA.forEach(d=>{const li=document.createElement('li');
    li.dataset.id=d.id; if(d.id===cur)li.className='sel';
    const a=Object.values(d.models)[0]||{};
    li.innerHTML='<span class="nm'+(d.cc?' cc':d.nc?' nc':'')+'">'+(d.name||d.id)
      +'</span><span class="tw">'+(a.town||'')+'</span>';
    li.onclick=()=>{if(cur===d.id)return;cur=d.id;shown=null;
      document.getElementById('out').innerHTML='';document.getElementById('prog').innerHTML='';
      cards()}; list.appendChild(li)});
}

function cards(){
  renderList();
  const d=DATA.find(x=>x.id===cur); if(!d){document.getElementById('cards').innerHTML='';return}
  const m=Object.values(d.models)[0]||{};
  const opts=MODELS.filter(([t])=>d.models[t]).map(([t,label,ver])=>
    '<option value="'+ver+'">'+label+'</option>').join('');
  document.getElementById('cards').innerHTML=
     '<div class="card" data-id="'+d.id+'"><h2'+(d.cc?' class="cc"':d.nc?' class="nc"':'')+'>'
    +(d.name||d.id)+'</h2>'
    +'<div class="badges"><span class="b">'+(m.town||'')+'</span></div>'
    +'<div class="txt">'+d.caption+'</div>'
    +'<div class="runbar"><button class="btn go" data-id="'+d.id+'">&#9654; Generate live</button>'
    +'<span class="fld">model <select class="md">'+opts+'</select></span>'
    +'<span class="fld">vehicle <select class="vh">'
    +VEHICLES.map(([v,label])=>'<option value="'+v+'">'+label+'</option>').join('')
    +'</select></span>'
    +'<span class="fld" id="shownby" style="display:none"></span></div></div>';
  document.querySelectorAll('.btn.go').forEach(b=>{b.disabled=!!poll;
    b.onclick=()=>start(b.closest('.card'),b.dataset.id)});
  // selecting a different model only changes what the NEXT run uses; whatever
  // is already on screen stays until Generate is pressed or the scene changes.
  const md=document.querySelector('.md');
  if(md){ if(shown) md.value=shown.ver; md.onchange=()=>mark(); }
  mark();
}

function mark(){
  const md=document.querySelector('.md'); const tag=document.getElementById('shownby');
  if(!tag) return;
  tag.textContent = shown ? ('showing: '+shown.label) : '';
  tag.style.display = shown ? '' : 'none';
  const b=document.querySelector('.btn.go');
  if(b&&!poll) b.textContent = (shown && md && md.value!==shown.ver)
    ? '\u25b6 Generate with this model' : '\u25b6 Generate live';
}

async function health(){
  try{const j=await (await fetch('api/health')).json(); ready=j.worker_ready;
    document.getElementById('hstat').innerHTML = ready
      ? '<span style="color:var(--ok)">&#9679;</span> GPU ready'+(j.queued?' &middot; '+j.queued+' queued':'')
      : '<span style="color:var(--acc)">&#9679;</span> <span class="dots">warming up the GPU</span>';
  }catch(e){}
}

async function start(card,id){
  const model=card.querySelector('.md').value;
  const vehicle=card.querySelector('.vh').value;
  // fixed, not user-facing: the seed only places the scene the case was built for
  const d=DATA.find(x=>x.id===id)||{}, m=Object.values(d.models||{})[0]||{};
  const seed=m.seed||42, steps=m.frames||100;
  const prog=document.getElementById('prog');
  document.getElementById('out').innerHTML='';
  prog.innerHTML='<div class="prog buf"><span class="spin"></span>'
    +'<span class="phase">Sending the job to the GPU<span class="dots"></span></span></div>';
  let r;
  try{ r=await (await fetch('api/run',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({scenario:id,model:model,seed:seed,steps:steps,
                            vehicle:vehicle})})).json() }
  catch(e){ prog.innerHTML='<div class="prog err">could not reach the server</div>'; return }
  if(r.error){ prog.innerHTML='<div class="prog err">'+r.error+'</div>'; return }
  document.querySelectorAll('.btn.go').forEach(b=>b.disabled=true);
  if(poll) clearInterval(poll);
  remember(r.id);
  poll=setInterval(()=>tick(r.id),1500); tick(r.id);
}

async function tick(jid){
  const prog=document.getElementById('prog');
  let s; try{ s=await (await fetch('api/status?id='+encodeURIComponent(jid))).json() }catch(e){ return }
  if(s.phase==='done'){
    clearInterval(poll); poll=null; remember(null);
    document.querySelectorAll('.btn.go').forEach(b=>b.disabled=false);
    const v=s.videos||{};
    const mm=MODELS.find(m=>m[1]===s.model)||MODELS.find(m=>m[2]===s.version);
    const vv=VEHICLES.find(v=>v[0]===s.vehicle);
    shown={ver:(mm||[])[2]||'1',
           label:(s.model||'Alpamayo')+(vv?' \u00b7 '+vv[1]:'')};
    document.getElementById('out').innerHTML='<div class="row3">'+VIEWS.filter(([k])=>v[k])
      .map(([k,label])=>'<div class="view"><h3>'+label+' &mdash; live</h3><video src="'+v[k]
        +'?t='+Date.now()+'" controls autoplay loop muted playsinline></video></div>').join('')+'</div>';
    prog.innerHTML='<div class="prog"><div class="phase" style="color:var(--ok)">&#10003; done</div>'
      +'<div class="badges" style="margin-bottom:0">'
      +'<span class="b">mean speed '+(s.speed_mean||0)+' m/s</span>'
      +'<span class="b">'+(s.wall_s||0)+'s wall</span>'
      +'<span class="b">live rendering</span></div></div>';
    mark();
    return;
  }
  if(s.phase==='error'){
    clearInterval(poll); poll=null; remember(null);
    document.querySelectorAll('.btn.go').forEach(b=>b.disabled=false);
    prog.innerHTML='<div class="prog"><div class="phase err">failed</div><div class="muted">'
      +(s.error||'')+'</div></div>'; return;
  }
  const L={queued:['Reserving the GPU','the run starts as soon as the card is free'],
    compiling:['Compiling the Scenic scenario',''],
    simulating:['Spawning the world in CARLA','placing the ego vehicle and the other actors'],
    rendering:['Alpamayo is driving','predicting a trajectory and following it, step by step'],
    encoding:['Encoding the three camera views','almost there']}[s.phase]||[s.phase,''];
  const pct=s.total?Math.round(100*(s.step||0)/s.total):0;
  prog.innerHTML='<div class="prog buf"><span class="spin"></span>'
    +'<span class="phase">'+L[0]+'<span class="dots"></span></span>'
    +'<div class="bar"><i style="width:'+pct+'%"></i></div>'
    +'<div class="stmt">'+L[1]+'</div>'
    +'<div class="sub2">step '+(s.step||0)+' of '+(s.total||'?')
    +(s.inference_s?' &middot; last inference '+s.inference_s+'s':'')
    +(s.speed_kmh!=null?' &middot; '+s.speed_kmh+' km/h':'')+'</div></div>';
}
cards(); health(); setInterval(health,5000);
const rj=remembered();
if(rj){ document.querySelectorAll('.btn.go').forEach(b=>b.disabled=true);
        poll=setInterval(()=>tick(rj),1500); tick(rj); }
</script></div></body></html>"""


def emit(tpl, path):
    page = (tpl.replace("__CSS__", CSS)
               .replace("__REEL__", REEL_SRC)
               .replace("__PLCOLS__", reel_columns())
               .replace("__DATA__", json.dumps(data))
               .replace("__MODELS__", json.dumps([[t, l, v] for t, l, v in MODELS]))
               .replace("__VIEWS__", json.dumps(VIEWS))
               .replace("__VEHICLES__", json.dumps(VEHICLES)))
    with open(path, "w") as f:
        f.write(page)
    return path


emit(SHOWCASE_HTML, os.path.join(GAL, "live.html"))
emit(STUDIO_HTML, os.path.join(GAL, "studio.html"))
if not os.path.exists(os.path.join(GAL, REEL_SRC)):
    print(f"  note: {REEL_SRC} not built yet - live.html shows an empty player "
          "until cornercase/build_reel.py has run")
print(f"built {GAL}/live.html + studio.html: {len(data)} scenario(s)")
for d in data:
    print(f"  {d['name']} = {d['id']}: {d['caption'][:70]}")
