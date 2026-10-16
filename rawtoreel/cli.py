"""rawtoreel command line.

    rawtoreel intake <job> <clip.mp4> [--title "..."]   step 1
    rawtoreel run <job> [--format youtube] [--music]   steps 2-7 (or --from N to resume)
    rawtoreel step <n> <job> [--format youtube]        one step by number
    rawtoreel status <job>
    rawtoreel formats
    rawtoreel sample                                    make a synthetic test clip (needs piper + ffmpeg)
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import STEPS, __version__
from .config import available_formats, load_format, load_style
from .job import Job

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Raw clip in, finished reel out.")
console = Console()


def _job(name: str) -> Job:
    j = Job(name)
    if not j.dir.exists():
        console.print(f"[red]No job named '{name}'.[/] Start one with: rawtoreel intake {name} <clip>")
        raise typer.Exit(2)
    return j


def _run_step(n: int, job: Job, fmt_name: str, style_name: str, *, music: bool, prune: bool) -> None:
    from .steps import captions, export, graphics, rough_cut, second_pass
    from .steps import music as music_step

    fmt = load_format(fmt_name)
    style = load_style(style_name)
    name = STEPS[n - 1]
    console.rule(f"[bold]step {n}/7 - {name}")
    if name == "intake":
        console.print("Intake takes a file: rawtoreel intake <job> <clip>")
        raise typer.Exit(2)
    if name == "rough_cut":
        rough_cut.run(job)
    elif name == "graphics":
        graphics.run(job, fmt, style)
    elif name == "second_pass":
        second_pass.run(job)
        if job.notes.exists():  # a recut invalidates graphics; redo them
            graphics.run(job, fmt, style)
    elif name == "captions":
        captions.run(job, fmt, style)
    elif name == "music":
        if music:
            music_step.run(job)
        else:
            if job.music.exists():
                job.music.unlink()
            job.mark("music", skipped=True)
            console.print("[dim]music skipped (pass --music to add a bed)[/]")
    elif name == "export":
        export.run(job, fmt, prune=prune)


@app.callback()
def _version(version: bool = typer.Option(False, "--version", is_eager=True)) -> None:
    if version:
        console.print(f"rawtoreel {__version__}")
        raise typer.Exit()


@app.command()
def intake(job: str, clip: Path, title: str = typer.Option(None, help="Title shown on the title card"),
           speaker: str = typer.Option(None), role: str = typer.Option(None)) -> None:
    """Step 1: copy a raw clip into projects/<job>/raw/."""
    from .steps import intake as intake_step

    j = Job(job)
    j.dir.mkdir(parents=True, exist_ok=True)
    meta = intake_step.run(j, clip, title=title)
    if speaker or role:
        m = j.read_manifest()
        if speaker:
            m["speaker"] = speaker
        if role:
            m["role"] = role
        j.write_manifest(m)
    console.print(f"[green]intake ok[/] {meta['file']} {meta['width']}x{meta['height']} {meta['duration']:.1f}s")


@app.command()
def run(job: str, format: str = typer.Option("youtube", "--format", "-f"),
        style: str = typer.Option("default"), music: bool = typer.Option(False, "--music"),
        from_step: int = typer.Option(2, "--from", min=2, max=7),
        prune: bool = typer.Option(False, help="Delete bulky intermediates after export")) -> None:
    """Steps 2-7 in order. Use --from N to resume after editing notes.json or presets."""
    j = _job(job)
    if format not in available_formats():
        console.print(f"[red]unknown format[/] {format}; try: {', '.join(available_formats())}")
        raise typer.Exit(2)
    for n in range(from_step, 8):
        _run_step(n, j, format, style, music=music, prune=prune)
    console.print(f"\n[bold green]done[/] -> {j.output(format)}")


@app.command()
def step(n: int = typer.Argument(..., min=1, max=7), job: str = typer.Argument(...),
         format: str = typer.Option("youtube", "--format", "-f"), style: str = typer.Option("default"),
         music: bool = typer.Option(True, "--music/--no-music")) -> None:
    """Run exactly one step (2-7) by number."""
    _run_step(n, _job(job), format, style, music=music, prune=False)


@app.command()
def status(job: str) -> None:
    """Show which steps have run for a job."""
    j = _job(job)
    t = Table(title=f"{j.name} - {j.title}")
    t.add_column("#")
    t.add_column("step")
    t.add_column("done")
    t.add_column("info")
    m = j.read_manifest()
    for i, (s, done) in enumerate(j.status(), 1):
        info = {k: v for k, v in m["steps"].get(s, {}).items() if k != "done_at"}
        t.add_row(str(i), s, "[green]yes[/]" if done else "[dim]no[/]", ", ".join(f"{k}={v}" for k, v in info.items()))
    console.print(t)


@app.command()
def formats() -> None:
    """List format presets."""
    for f in available_formats():
        p = load_format(f)
        console.print(f"{f:10s} {p.width}x{p.height}  captions={p.captions.mode:9s} graphics={p.graphics.style}")


@app.command()
def sample(out: Path = typer.Option(Path("sample/sample.mp4"), help="Where to write the clip")) -> None:
    """Generate a synthetic narrated test clip (needs `piper` TTS; used by CI)."""
    from .sample import make_sample

    path = make_sample(out)
    console.print(f"[green]sample written[/] {path}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
