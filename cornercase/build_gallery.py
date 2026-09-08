"""Build the Alpamayo comparison gallery: model selector + 3 synchronized views.

  python cornercase/build_gallery.py [results_dir ...] [--only id,id]   (default outputs/runs)

Writes outputs/site/alpamayo.html and copies each run's clips next to it.
Later directories win, so a fresh batch overrides an earlier one.
"""
import json, os, re, shutil, sys, html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

# --only id,id,...  restricts the page to these scenarios.
ONLY = None
args = list(sys.argv[1:])
if "--only" in args:
    i = args.index("--only")
    ONLY = {x.strip() for x in args[i + 1].split(",") if x.strip()}
    del args[i:i + 2]
SRCS = [os.path.abspath(a) for a in args] or [paths.RUNS]
GAL  = paths.SITE
VID  = os.path.join(GAL, "alpamayo")
os.makedirs(VID, exist_ok=True)


def display_name(sid):
    return sid


MODELS = [("r1", "Alpamayo 1 (R1)"), ("v15", "Alpamayo 1.5")]
VIEWS  = [("bev", "Bird's-eye view"), ("fpv", "First-person view"), ("tpv", "Third-person view")]

rows, src_of = {}, {}
for SRC in SRCS:
    for tag, _ in MODELS:
        f = os.path.join(SRC, f"results_{tag}.jsonl")
        if not os.path.exists(f): continue
        for line in open(f):
            line = line.strip()
            if not line.startswith("{"): continue
            try: r = json.loads(line)
            except Exception: continue
            if r.get("status") not in ("ok", "partial"): continue
            if ONLY is not None and r["id"] not in ONLY: continue
            rows.setdefault(r["id"], {})[tag] = r
            src_of[(r["id"], tag)] = SRC

data = []
def sort_key(s):
    # curated cases first, then Carlamayo's own random-spawn setting
    return (1 if s.startswith("random_spawn") else 0, s)


for sid in sorted(rows, key=sort_key):
    entry = {"id": sid, "label": display_name(sid), "models": {}}
    for tag, label in MODELS:
        r = rows[sid].get(tag)
        if not r: continue
        views = {}
        for v, _ in VIEWS:
            src = os.path.join(src_of[(sid, tag)], f"{sid}__{tag}__{v}.mp4")
            if os.path.exists(src) and os.path.getsize(src) > 5000:
                dst = os.path.join(VID, f"{sid}__{tag}__{v}.mp4")
                if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                    shutil.copy2(src, dst)
                views[v] = f"alpamayo/{sid}__{tag}__{v}.mp4"
        if not views: continue
        entry["models"][tag] = {
            "label": label, "views": views,
            "town": r.get("town", ""), "frames": r.get("frames", 0),
            "coc": r.get("coc_last", r.get("cot_last", "")),
            "cocn": r.get("coc_emissions", 0),
            "inf": r.get("inference_mean_s", 0), "calls": r.get("inference_calls", 0),
            "wall": r.get("wall_s", 0), "seed": r.get("seed", 42),
            "spd": r.get("speed_mean", 0), "tgt": r.get("target_kmh_mean", 0),
            "mode": r.get("speed_mode", "carlamayo"), "nav": r.get("nav_text", ""),
            "desc": r.get("description", ""), "n": r.get("traj_samples", 1) or 1,
            "col": r.get("collisions"), "colf": r.get("first_collision_frame"),
            "colw": r.get("first_collision_with"),
        }
    if entry["models"]: data.append(entry)

page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alpamayo on Corner-Case Scenarios</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#252a34;--fg:#e6e9ef;--dim:#9aa3b2;--acc:#5aa9ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;height:100vh;overflow:hidden}
.wrap{display:flex;height:100vh}
aside{width:320px;flex:0 0 320px;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column}
header{padding:16px;border-bottom:1px solid var(--line)}
h1{margin:0 0 2px;font-size:15px}
.sub{color:var(--dim);font-size:11.5px}
.controls{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:8px}
select,input{width:100%;background:#0f1218;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:8px 10px;font-size:13px}
select:focus,input:focus{outline:none;border-color:var(--acc)}
ul{list-style:none;margin:0;padding:6px;overflow-y:auto;flex:1}
li{padding:8px 10px;border-radius:6px;cursor:pointer;display:flex;gap:8px;align-items:baseline}
li:hover{background:#1e222b}
li.sel{background:#23324a;box-shadow:inset 2px 0 0 var(--acc)}
.nm{font-weight:600;font-size:12.5px}
.tw{color:var(--dim);font-size:10.5px;margin-left:auto}
main{flex:1;display:flex;flex-direction:column;min-width:0;padding:20px 24px;overflow-y:auto}
h2{margin:0 0 8px;font-size:18px}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.b{background:#1e222b;border:1px solid var(--line);color:var(--dim);border-radius:999px;padding:3px 10px;font-size:11px}
.b.warn{background:#3a1e1e;border-color:#7a3b3b;color:#f0b4b4}
.models{display:flex;gap:10px;margin:6px 0 16px}
.mbtn{background:#1a1e27;border:1.5px solid var(--line);color:var(--dim);border-radius:8px;
      padding:10px 20px;font-size:13.5px;font-weight:600;cursor:pointer;transition:.12s}
.mbtn:hover{border-color:#3d4757;color:var(--fg)}
.mbtn.on{background:#1d3a5f;border-color:var(--acc);color:#fff;box-shadow:0 0 0 3px rgba(90,169,255,.15)}
.mbtn.off{opacity:.4;cursor:not-allowed}
.cot{background:#141a13;border-left:3px solid #4a7c3f;padding:10px 14px;border-radius:0 6px 6px 0;
     margin-bottom:16px;color:#cfe3c8;font-size:12.5px;max-width:90ch}
.cot{font-style:italic}
.cocn{display:block;margin-top:6px;font-style:normal;color:#7f9a78;font-size:11px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.mode{margin:10px 0 16px;padding:9px 13px;border-left:3px solid #6f5bd0;background:#181626;color:#c9c2e8;border-radius:0 6px 6px 0;font-size:12px;max-width:92ch;line-height:1.5}
.mode b{color:#a595f0}
.pair h4{margin:0 0 5px;font-size:10.5px;letter-spacing:.5px;text-transform:uppercase;font-weight:600}
.ask{padding:10px 14px;border-radius:0 6px 6px 0;font-size:12.5px;line-height:1.45;max-width:92ch}
.ask{background:#171a22;border-left:3px solid #4a6a8c;color:#c3d2e0}
.ask h4{color:#7ba7d4}
.said{background:#141a13;border-left:3px solid #4a7c3f;color:#cfe3c8}
.said h4{color:#8fd47f}
@media(max-width:900px){.pair{grid-template-columns:1fr}}
.views{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px}
.view h3{margin:0 0 6px;font-size:13px;color:var(--dim);font-weight:600;letter-spacing:.3px;text-transform:uppercase}
video{width:100%;border-radius:8px;background:#000;border:1px solid var(--line);display:block}
.note{margin-top:22px;padding:12px 14px;border-left:3px solid #6b5b1f;background:#1c1a12;color:#cfc39a;font-size:12px;max-width:90ch;border-radius:0 6px 6px 0}
.empty{color:var(--dim);margin:auto;text-align:center}
</style></head><body>
<div class="wrap">
 <aside>
  <header><h1>Alpamayo &times; Corner Cases</h1><div class="sub">__N__ scenarios rendered &middot; CARLA 0.9.16</div></header>
  <div class="controls">
   <select id="dd"></select>
   <input id="q" type="search" placeholder="Filter scenarios&hellip;">
  </div>
  <ul id="list"></ul>
 </aside>
 <main><div id="stage" class="empty">Select a scenario.</div></main>
</div>
<script>
const DATA = __DATA__;
const MODELS = __MODELS__, VIEWS = __VIEWS__;
const MODES = {
 'carlamayo': "Carlamayo's own heuristic \u2014 target speed = clip(10 + 0.5 \u00d7 path length, 10, 35) km/h. Because Alpamayo's output is a 6.4 s plan, slowing down shortens the path, which the controller reads as \u201cslow down more\u201d.",
 'plan':      "Target speed = the whole 6.4 s path length \u00f7 6.4 s. Removes the 10 km/h floor so the car can stop \u2014 but keeps the same length\u2192speed coupling, so it can also fail to start again.",
 'planvel':   "THE FIX \u2014 target speed = the velocity the plan actually carries over its first 1.5 s (waypoints are 0.1 s apart), then EMA-smoothed. Decouples \u201chow fast\u201d from \u201chow far\u201d, so a planned slow-down reads as a slow-down instead of a stop."
};
const list=document.getElementById('list'), dd=document.getElementById('dd'),
      q=document.getElementById('q'), stage=document.getElementById('stage');
let cur=null, curModel='r1';
DATA.forEach(d=>{const o=document.createElement('option');o.value=d.id;
  o.textContent=d.label+'  ·  '+Object.keys(d.models).length+' model(s)';dd.appendChild(o);});
function renderList(items){
  list.innerHTML='';
  items.forEach(d=>{
    const li=document.createElement('li'); li.dataset.id=d.id;
    if(d.id===cur) li.className='sel';
    const any=Object.values(d.models)[0]||{};
    li.innerHTML='<span class="nm">'+d.label+'</span><span class="tw">'+(any.town||'')+'</span>';
    li.onclick=()=>show(d.id,curModel); list.appendChild(li);
  });
}
function show(id, model){
  const d=DATA.find(x=>x.id===id); if(!d) return;
  cur=id; dd.value=id;
  if(!d.models[model]) model=Object.keys(d.models)[0];
  curModel=model;
  const m=d.models[model];
  let btns=MODELS.map(([tag,label])=>{
    const has=!!d.models[tag];
    return '<button class="mbtn '+(tag===model?'on':(has?'':'off'))+'" '+(has?'':'disabled ')+
           'data-m="'+tag+'">'+label+'</button>';
  }).join('');
  let vids=VIEWS.map(([v,label])=>{
    const src=m.views[v];
    if(!src) return '';
    return '<div class="view"><h3>'+label+'</h3><video src="'+src+
           '" controls autoplay loop muted playsinline></video></div>';
  }).join('');
  stage.className='';
  stage.innerHTML='<h2>'+d.label+'</h2>'
   +'<div class="badges"><span class="b">'+m.town+'</span><span class="b">seed '+m.seed+'</span>'
   +'<span class="b">'+m.frames+' frames</span>'
   +'<span class="b">'+m.calls+' inferences @ '+m.inf+'s</span>'
   +'<span class="b">mean '+(m.spd*3.6).toFixed(1)+' km/h</span>'
   +'<span class="b">PID target '+m.tgt+' km/h</span>'
   +'<span class="b">speed mode: '+m.mode+'</span>'
   +'<span class="b">traj samples: '+m.n+'</span>'
   +(m.col===undefined||m.col===null?'':'<span class="b'+(m.col?' warn':'')+'">'
       +(m.col?m.col+' collision'+(m.col>1?'s':'')+' (first frame '+m.colf+', '+String(m.colw).split('.').slice(1).join('.')+')':'no collision')+'</span>')
   +'<span class="b">'+m.wall+'s wall</span></div>'
   +'<div class="models">'+btns+'</div>'
   +(m.desc?'<div class="ask"><h4>What the scenario asks for</h4>'+m.desc+'</div>':'')
   +'<div class="mode"><b>Speed control:</b> '+(MODES[m.mode]||m.mode)+'</div>'
   +'<div class="views">'+vids+'</div>'
   +'<div class="note"><strong>Setup:</strong> Scenic samples the scene and drives every adversary; '
   +'the <em>ego</em> is driven by the selected Alpamayo model via PID over its predicted trajectory. '
   +'Both models run the <strong>same seed</strong>, so initial conditions and adversary behaviour are '
   +'identical &mdash; any difference is the model. The first-person view carries the projected trajectory '
   +'and CoC (Chain-of-Causation) overlay. Corner cases are written in Scenic from text specs '
   +'(scenarios/curated); random_spawn runs use Carlamayo\'s own Town03 traffic setting.</div>';
  stage.querySelectorAll('.mbtn[data-m]').forEach(b=>{
    if(!b.disabled) b.onclick=()=>show(id, b.dataset.m);
  });
  [...list.children].forEach(li=>li.className = li.dataset.id===id?'sel':'');
}
q.oninput=()=>{const s=q.value.toLowerCase().trim();
  renderList(!s?DATA:DATA.filter(d=>(d.label+' '+d.id).toLowerCase().includes(s)));};
dd.onchange=()=>show(dd.value,curModel);
renderList(DATA); if(DATA.length) show(DATA[0].id,'r1');
</script></body></html>
"""
page = (page.replace("__DATA__", json.dumps(data))
            .replace("__MODELS__", json.dumps(MODELS))
            .replace("__VIEWS__", json.dumps(VIEWS))
            .replace("__N__", str(len(data))))
out = os.path.join(GAL, "alpamayo.html")
with open(out, "w") as fh: fh.write(page)
print(f"built {out}: {len(data)} scenarios")
for d in data:
    print(f"  {d['label']}: " + ", ".join(f"{t}({len(v['views'])} views)" for t,v in d["models"].items()))
