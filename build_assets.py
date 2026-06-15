# -*- coding: utf-8 -*-
"""Baut die CLI/TUI visual-identity fuer Hunch: ASCII-logo + gedicht -> banner.png + logo.png.
Terminal-look, orange-gold. Rendert HTML via headless Chrome."""
import subprocess, pathlib, tempfile, html as _html
import pyfiglet

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "assets"; ASSETS.mkdir(exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

ascii_big = pyfiglet.figlet_format("hunch", font="ansi_shadow").rstrip("\n")
ascii_small = pyfiglet.figlet_format("hunch", font="small").rstrip("\n")

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
:root{
  --bg:#0a0a0c; --win:#101013; --bar:#17171b; --bd:#2a2a31;
  --orange:#ff8a1e; --gold:#ffd24a; --amber:#ffb43e;
  --dim:#9c8657; --dimmer:#6c5d3e; --green:#7ee7a3; --comment:#6a6a73;
}
body{background:radial-gradient(1200px 700px at 70% -10%, #1a140a 0%, var(--bg) 55%);font-family:'JetBrains Mono',monospace;color:#e8e3d6}
.win{position:absolute;background:linear-gradient(180deg,#0f0f12,#0b0b0e);border:1px solid var(--bd);
     border-radius:14px;box-shadow:0 30px 90px rgba(0,0,0,.65), inset 0 1px 0 rgba(255,255,255,.04)}
.bar{height:42px;display:flex;align-items:center;gap:9px;padding:0 16px;border-bottom:1px solid var(--bd);
     background:linear-gradient(180deg,#1a1a1f,#141418);border-radius:14px 14px 0 0}
.dot{width:12px;height:12px;border-radius:50%}
.r{background:#ff5f57}.y{background:#febc2e}.g{background:#28c840}
.bartitle{margin-left:14px;color:#8a8a93;font-size:13px;letter-spacing:.04em}
.logo{font-weight:800;line-height:1.0;white-space:pre;
  background:linear-gradient(120deg,var(--orange) 0%,var(--amber) 45%,var(--gold) 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 2px 18px rgba(255,150,40,.30))}
.tag{color:var(--dim);letter-spacing:.02em}
.flow{color:var(--gold);font-weight:700}
.flow .arr{color:var(--dimmer)}
.box{border:1px solid #3a2f17;border-radius:10px;background:rgba(255,180,60,.03);position:relative}
.boxlabel{position:absolute;top:-11px;left:18px;background:#0c0b0e;padding:0 10px;color:var(--orange);font-size:13px;letter-spacing:.08em}
.poem{color:#e9dcc0;white-space:pre-wrap;line-height:1.6}
.poem .em{color:var(--gold)}
.prompt .p{color:var(--green)} .prompt .c{color:var(--orange)} .prompt .cur{color:var(--gold)}
.comment{color:var(--comment)}
"""

def render(html, out, w, h):
    hp = ASSETS / "_tmp.html"; hp.write_text(html, encoding="utf-8")
    udd = tempfile.mkdtemp(prefix="hunch_")
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",f"--user-data-dir={udd}",
        "--force-device-scale-factor=2",f"--window-size={w},{h}","--default-background-color=00000000",
        "--virtual-time-budget=4000",f"--screenshot={out}",hp.as_uri()],capture_output=True,text=True,timeout=120)
    print("ok", out)

# ---------- BANNER 1280x690 ----------
poem_html = _html.escape(POEM).replace("hunch","<span class='em'>hunch</span>")
banner = f"""<!doctype html><html><head><meta charset='utf-8'><style>{CSS}
.win{{left:44px;top:42px;width:1192px;height:606px}}
.body{{padding:26px 46px}}
.logo{{font-size:30px;margin:8px 0 2px;line-height:1.05}}
.tag{{font-size:19px;margin:14px 0 4px}}
.flow{{font-size:17px;margin:6px 0 20px}}
.box{{margin:4px 0 18px;padding:22px 28px 20px}}
.poem{{font-size:16px}}
.prompt{{font-size:16px;margin-top:4px}}
</style></head><body>
<div class='win'>
  <div class='bar'><span class='dot r'></span><span class='dot y'></span><span class='dot g'></span>
    <span class='bartitle'>hunch — ~/  ·  a local proactive AI partner</span></div>
  <div class='body'>
    <div class='logo'>{_html.escape(ascii_small)}</div>
    <div class='tag'>// a quiet second mind that watches, connects, and whispers.</div>
    <div class='flow'>watch <span class='arr'>→</span> graph <span class='arr'>→</span> connect <span class='arr'>→</span> nudge</div>
    <div class='box'><span class='boxlabel'>the pitch, in verse</span><div class='poem'>{poem_html}</div></div>
    <div class='prompt'><span class='p'>~</span> <span class='c'>❯</span> hunch --whisper<span class='cur'>▌</span>
      &nbsp;&nbsp;<span class='comment'># 100% local · no cloud · your data stays yours</span></div>
  </div>
</div></body></html>"""
render(banner, str(ASSETS/"banner.png"), 1280, 690)

# ---------- LOGO 640x640 ----------
logo = f"""<!doctype html><html><head><meta charset='utf-8'><style>{CSS}
.win{{left:70px;top:70px;width:500px;height:500px}}
.body{{padding:34px 38px;display:flex;flex-direction:column;height:calc(100% - 42px)}}
.logo{{font-size:40px;margin:18px 0 0}}
.tag{{font-size:15px;margin:18px 0 0;color:var(--dim)}}
.flow{{font-size:14px;margin:14px 0 0}}
.spacer{{flex:1}}
.prompt{{font-size:16px}}
</style></head><body>
<div class='win'>
  <div class='bar'><span class='dot r'></span><span class='dot y'></span><span class='dot g'></span>
    <span class='bartitle'>hunch</span></div>
  <div class='body'>
    <div class='logo'>{_html.escape(ascii_small)}</div>
    <div class='tag'>a quiet second mind.</div>
    <div class='flow'>watch <span class='arr'>→</span> connect <span class='arr'>→</span> nudge</div>
    <div class='spacer'></div>
    <div class='prompt'><span class='p'>~</span> <span class='c'>❯</span> <span class='cur'>▌</span></div>
  </div>
</div></body></html>"""
render(logo, str(ASSETS/"logo.png"), 640, 640)
print("DONE")
