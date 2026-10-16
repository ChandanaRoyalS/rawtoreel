"""Build a HyperFrames composition from a graphics plan and render it to a transparent WebM.

Why HyperFrames: the composition is plain HTML + a paused GSAP timeline, rendered frame by frame
in headless Chromium, so the same plan always produces the same pixels. We generate the HTML here
(no runtime DOM building) so `npx hyperframes lint` can validate it as a static file.

Layout of the generated project (projects/<job>/overlay-src/<format>/):
    index.html     the composition
    gsap.min.js    vendored from node_modules so renders work offline
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

from ..config import REPO_ROOT, FormatPreset, StylePreset

console = Console(stderr=True)


class RenderError(RuntimeError):
    pass


# --------------------------------------------------------------------------- HTML generation

def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_html(plan: dict, fmt: FormatPreset, style: StylePreset) -> str:
    W, H = fmt.width, fmt.height
    portrait = fmt.portrait
    beats = plan["beats"]
    duration = plan["duration"]
    g = fmt.graphics

    clips: list[str] = []
    tweens: list[str] = []
    for i, b in enumerate(beats):
        cid = f"b{i}"
        s, d = b["start"], b["duration"]
        if b["type"] == "title":
            clips.append(
                f'<section class="clip title" data-start="{s}" data-duration="{d}" data-track-index="1">'
                f'<div id="{cid}" class="card title-card"><h1>{_esc(b["text"])}</h1>'
                + (f'<p>{_esc(b["sub"])}</p>' if b.get("sub") else "")
                + "</div></section>"
            )
            tweens.append(
                f'tl.fromTo("#{cid}", {{y: 40, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.55, ease: "power3.out"}}, {s});'
                f'tl.to("#{cid}", {{y: -16, opacity: 0, duration: 0.4, ease: "power2.in"}}, {s + d - 0.4});'
            )
        elif b["type"] == "lower_third":
            clips.append(
                f'<section class="clip lt" data-start="{s}" data-duration="{d}" data-track-index="2">'
                f'<div id="{cid}" class="lower-third"><span class="bar"></span>'
                f'<div class="lt-text"><strong>{_esc(b["name"])}</strong>'
                + (f'<em>{_esc(b["role"])}</em>' if b.get("role") else "")
                + "</div></div></section>"
            )
            tweens.append(
                f'tl.fromTo("#{cid}", {{x: -60, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.5, ease: "power3.out"}}, {s});'
                f'tl.to("#{cid}", {{x: -40, opacity: 0, duration: 0.35, ease: "power2.in"}}, {s + d - 0.35});'
            )
        elif b["type"] == "chapter":
            clips.append(
                f'<section class="clip chapter" data-start="{s}" data-duration="{d}" data-track-index="3">'
                f'<div id="{cid}" class="pill">{_esc(b["text"])}</div></section>'
            )
            tweens.append(
                f'tl.fromTo("#{cid}", {{scale: 0.85, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.4, ease: "back.out(1.6)"}}, {s});'
                f'tl.to("#{cid}", {{opacity: 0, duration: 0.3}}, {s + d - 0.3});'
            )
        elif b["type"] == "callout":
            clips.append(
                f'<section class="clip callout" data-start="{s}" data-duration="{d}" data-track-index="4">'
                f'<div id="{cid}" class="callout-box">{_esc(b["text"])}</div></section>'
            )
            tweens.append(
                f'tl.fromTo("#{cid}", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.4, ease: "power3.out"}}, {s});'
                f'tl.to("#{cid}", {{opacity: 0, duration: 0.3}}, {s + d - 0.3});'
            )

    # Sizes scale with the short edge so the same preset reads well at 1080p and 4k.
    base = min(W, H) / 1080
    title_px = int((92 if portrait else 72) * base)
    sub_px = int((40 if portrait else 30) * base)
    lt_px = int((38 if portrait else 34) * base)
    pill_px = int((40 if portrait else 34) * base)
    pad = int(48 * base)
    # Generic stack on purpose: HyperFrames lint requires an @font-face for any named family,
    # and vendoring a font is a style-preset decision for later (see presets/style/README).
    font_stack = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'

    if portrait:
        title_pos = f"top: {g.safe_top + int(80 * base)}px; left: {pad}px; right: {pad}px;"
        lt_pos = f"bottom: {g.safe_bottom + int(240 * base)}px; left: {pad}px;"
        chapter_pos = f"top: {g.safe_top + int(40 * base)}px; left: 0; right: 0; display:flex; justify-content:center;"
        callout_pos = f"top: {g.safe_top + int(300 * base)}px; left: {pad}px; right: {pad}px;"
    else:
        title_pos = f"bottom: {int(200 * base)}px; left: {int(96 * base)}px; max-width: 60%;"
        lt_pos = f"bottom: {int(110 * base)}px; left: {int(96 * base)}px;"
        chapter_pos = f"top: {int(72 * base)}px; left: 0; right: 0; display:flex; justify-content:center;"
        callout_pos = f"top: {int(120 * base)}px; right: {int(96 * base)}px; max-width: 34%;"

    css = f"""
      html, body {{ margin: 0; background: transparent; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden;
               font-family: {font_stack}; color: {style.ink}; }}
      .clip {{ position: absolute; inset: 0; pointer-events: none; }}
      .card {{ position: absolute; {title_pos}
               padding: {int(28 * base)}px {int(36 * base)}px; border-radius: {int(24 * base)}px;
               background: rgba(11, 15, 20, 0.62); backdrop-filter: blur(18px);
               border: 1px solid rgba(255,255,255,0.14);
               box-shadow: 0 {int(20 * base)}px {int(60 * base)}px rgba(0,0,0,0.35); }}
      .card h1 {{ margin: 0; font-size: {title_px}px; line-height: 1.08; font-weight: 800;
                 letter-spacing: -0.02em; }}
      .card p {{ margin: {int(12 * base)}px 0 0; font-size: {sub_px}px; color: {style.accent_2};
                font-weight: 600; }}
      .lower-third {{ position: absolute; {lt_pos} display: flex; align-items: stretch; gap: {int(18 * base)}px; }}
      .lower-third .bar {{ width: {int(10 * base)}px; border-radius: {int(6 * base)}px; background: {style.accent}; }}
      .lt-text {{ display: flex; flex-direction: column; justify-content: center;
                  padding: {int(14 * base)}px {int(24 * base)}px; border-radius: {int(14 * base)}px;
                  background: rgba(11, 15, 20, 0.7); }}
      .lt-text strong {{ font-size: {lt_px}px; font-weight: 800; }}
      .lt-text em {{ font-style: normal; font-size: {int(lt_px * 0.72)}px; opacity: 0.85; margin-top: 2px; }}
      .chapter {{ {chapter_pos} }}
      .pill {{ padding: {int(14 * base)}px {int(34 * base)}px; border-radius: 999px;
               background: {style.accent}; color: {style.paper}; font-weight: 800;
               font-size: {pill_px}px; letter-spacing: 0.01em; text-transform: uppercase; }}
      .callout-box {{ position: absolute; {callout_pos}
                      padding: {int(20 * base)}px {int(28 * base)}px; border-radius: {int(18 * base)}px;
                      background: {style.accent_2}; color: {style.paper}; font-weight: 700;
                      font-size: {int(36 * base)}px; line-height: 1.2; }}
    """

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <title>rawtoreel overlay - {_esc(plan.get("job", ""))} ({fmt.name})</title>
    <script src="gsap.min.js"></script>
    <style>{css}</style>
  </head>
  <body>
    <div id="root" data-composition-id="overlay" data-start="0" data-width="{W}" data-height="{H}" data-duration="{duration}">
      {"".join(clips)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      {"".join(tweens)}
      window.__timelines["overlay"] = tl;
    </script>
  </body>
</html>
"""


# --------------------------------------------------------------------------- rendering

def _node_modules() -> Path:
    return REPO_ROOT / "node_modules"


def ensure_node_deps() -> None:
    if (_node_modules() / "hyperframes").exists():
        return
    console.log("installing node dependencies (hyperframes, gsap)")
    proc = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(proc.stderr[-2000:])


def _browser_env(fallback: bool = False) -> dict:
    """HyperFrames manages its own headless Chrome (`npx hyperframes browser ensure`). When that is
    unavailable (offline machines, sandboxes) we point it at any Chrome/Chromium already installed."""
    env = dict(os.environ)
    env.setdefault("HYPERFRAMES_TELEMETRY", "0")
    if fallback and "HYPERFRAMES_BROWSER_PATH" not in env:
        for cand in (
            os.environ.get("CHROME_PATH"),
            "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
            shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
            shutil.which("chrome"),
        ):
            if cand and Path(cand).exists():
                env["HYPERFRAMES_BROWSER_PATH"] = cand
                break
    return env


def write_project(plan: dict, fmt: FormatPreset, style: StylePreset, project_dir: Path) -> Path:
    ensure_node_deps()
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "index.html").write_text(build_html(plan, fmt, style), encoding="utf-8")
    gsap = _node_modules() / "gsap" / "dist" / "gsap.min.js"
    if not gsap.exists():
        raise RenderError("gsap not installed: run `npm install` in the repo root")
    shutil.copy2(gsap, project_dir / "gsap.min.js")
    return project_dir


def lint(project_dir: Path) -> str:
    proc = subprocess.run(["npx", "hyperframes", "lint", str(project_dir)], cwd=REPO_ROOT,
                          capture_output=True, text=True, env=_browser_env())
    return (proc.stdout + proc.stderr).strip()


def render(project_dir: Path, output: Path, *, fps: int = 30, quality: str = "looks") -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "hyperframes", "render", str(project_dir), "--format", "webm",
           "--fps", str(fps), "--quality", quality, "--quiet", "--output", str(output)]
    console.log("[dim]$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=_browser_env())
    log = proc.stdout + proc.stderr
    if proc.returncode != 0 and "Chrome not found" in log:
        console.log("HyperFrames' own Chrome is missing; retrying with an installed browser")
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=_browser_env(fallback=True))
        log = proc.stdout + proc.stderr
    if proc.returncode != 0 or not output.exists():
        raise RenderError(log[-3000:])
    return output
