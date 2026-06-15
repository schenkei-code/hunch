# -*- coding: utf-8 -*-
"""Baut die Hunch visual-identity: owl-maskottchen (assets/owl.png) + lesbarer wordmark
-> logo.png (horizontal, transparent) + banner.png (terminal-hero). Orange-gold, CLI-look.
Rendert HTML via headless Chrome."""
import subprocess, pathlib, tempfile, base64, html as _html

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

OWL_B64 = base64.b64encode((ASSETS / "owl.png").read_bytes()).decode()
OWL = f"data:image/png;base64,{OWL_B64}"

POEM = """It doesn't ping. It doesn't shout.
It learns the way your days play out —
which tabs you reopen, which threads you keep,
the patterns you carry even in sleep.

It never foretells. It only connects
the old, half-forgotten your now expects.
And when the timing is gentle and true,
it leaves you a hunch — that feels like you."""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{--orange:#ff8a1e;--gold:#ffd24a;--amber:#ffb43e;--dim:#9c8657;--dimmer:#6c5d3e;
  --green:#7ee7a3;--comment:#6a6a73;--bd:#2a2a31}
body{font-family:'JetBrains Mono',monospace;color:#e8e3d6}
.wm{font-weight:800;letter-spacing:-.02em;line-height:.9;
  background:linear-gradient(110deg,var(--orange) 0%,var(--amber) 50%,var(--gold) 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 3px 22px rgba(255,150,40,.30))}
.cur{color:var(--gold);-webkit-text-fill-color:var(--gold)}
.owl{filter:drop-shadow(0 10px 30px rgba(255,120,20,.28))}
.tag{color:var(--dim)}
.flow{color:var(--gold);font-weight:700}.flow .arr{color:var(--dimmer)}
"""

def render(html, out, w, h, bg="00000000"):
    hp = ASSETS / "_tmp.html"; hp.write_text(html, encoding="utf-8")
    udd = tempfile.mkdtemp(prefix="hunch_")
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",f"--user-data-dir={udd}",
        "--force-device-scale-factor=2",f"--window-size={w},{h}",f"--default-background-color={bg}",
        "--virtual-time-budget=4000",f"--screenshot={out}",hp.as_uri()],capture_output=True,text=True,timeout=120)
    print("ok", out)

# ---------- LOGO horizontal (transparent) 1200x440 ----------
logo = f"""<!doctype html><html><head><meta charset='utf-8'><style>{CSS}
body{{width:1200px;height:440px;display:flex;align-items:center;justify-content:center;gap:40px}}
.owl{{height:360px}}
.txt{{display:flex;flex-direction:column;justify-content:center}}
.wm{{font-size:150px}}
.sub{{color:var(--dim);font-size:26px;margin-top:10px;letter-spacing:.02em}}
.flow{{font-size:22px;margin-top:14px}}
</style></head><body>
<img class='owl' src='{OWL}'>
<div class='txt'>
  <div class='wm'>hunch<span class='cur'>▌</span></div>
  <div class='sub'>// a quiet second mind</div>
  <div class='flow'>watch <span class='arr'>→</span> connect <span class='arr'>→</span> nudge</div>
</div></body></html>"""
render(logo, str(ASSETS/"logo.png"), 1200, 440)

# ---------- BANNER terminal-hero 1280x700 ----------
poem_html = _html.escape(POEM).replace("hunch","<span style='color:var(--gold)'>hunch</span>")
banner = f"""<!doctype html><html><head><meta charset='utf-8'><style>{CSS}
body{{background:radial-gradient(1200px 700px at 72% -12%, #1c1408 0%, #0a0a0c 55%)}}
.win{{position:absolute;left:44px;top:42px;width:1192px;height:616px;border:1px solid var(--bd);
  border-radius:14px;background:linear-gradient(180deg,#0f0f12,#0b0b0e);
  box-shadow:0 30px 90px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.04)}}
.bar{{height:42px;display:flex;align-items:center;gap:9px;padding:0 16px;border-bottom:1px solid var(--bd);
  background:linear-gradient(180deg,#1a1a1f,#141418);border-radius:14px 14px 0 0}}
.dot{{width:12px;height:12px;border-radius:50%}}.r{{background:#ff5f57}}.y{{background:#febc2e}}.g{{background:#28c840}}
.bartitle{{margin-left:14px;color:#8a8a93;font-size:13px;letter-spacing:.04em}}
.body{{padding:24px 44px;position:relative}}
.head{{display:flex;align-items:center;gap:26px;margin:2px 0 6px}}
.head .owl{{height:138px}}
.wm{{font-size:96px}}
.badge{{align-self:flex-start;margin-top:30px;color:var(--orange);border:1px solid #3a2f17;border-radius:6px;
  padding:3px 11px;font-size:13px;letter-spacing:.06em}}
.tag{{font-size:19px;margin:10px 0 4px}}
.flow{{font-size:17px;margin:6px 0 16px}}
.box{{border:1px solid #3a2f17;border-radius:10px;background:rgba(255,180,60,.03);position:relative;
  padding:20px 28px 18px;margin:2px 0 14px}}
.boxlabel{{position:absolute;top:-11px;left:18px;background:#0c0b0e;padding:0 10px;color:var(--orange);font-size:13px;letter-spacing:.08em}}
.poem{{color:#e9dcc0;white-space:pre-wrap;line-height:1.55;font-size:15px}}
.prompt{{font-size:16px}}.prompt .p{{color:var(--green)}}.prompt .c{{color:var(--orange)}}
.comment{{color:var(--comment)}}
</style></head><body>
<div class='win'>
  <div class='bar'><span class='dot r'></span><span class='dot y'></span><span class='dot g'></span>
    <span class='bartitle'>hunch — ~/  ·  a local proactive AI partner</span></div>
  <div class='body'>
    <div class='head'>
      <img class='owl' src='{OWL}'>
      <div class='wm'>hunch<span class='cur'>▌</span></div>
      <div class='badge'>v0.1 · 100% local</div>
    </div>
    <div class='tag'>// a quiet second mind that watches, connects, and whispers.</div>
    <div class='flow'>watch <span class='arr'>→</span> graph <span class='arr'>→</span> connect <span class='arr'>→</span> nudge</div>
    <div class='box'><span class='boxlabel'>the pitch, in verse</span><div class='poem'>{poem_html}</div></div>
    <div class='prompt'><span class='p'>~</span> <span class='c'>❯</span> hunch --whisper
      &nbsp;&nbsp;<span class='comment'># no cloud · your data stays yours</span></div>
  </div>
</div></body></html>"""
render(banner, str(ASSETS/"banner.png"), 1280, 700)
print("DONE")
