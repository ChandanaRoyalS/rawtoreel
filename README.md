# rawtoreel

**Raw clip in, finished reel out.** A fixed seven-step pipeline that turns a raw talking-head
recording into a finished video for YouTube, Instagram Reels, or TikTok: it transcribes the audio,
cuts the filler words, pauses and restarted sentences, adds graphics, burns in word-timed captions,
ducks background music under the voice, and exports the right size.

[![pipeline](https://github.com/ChandanaRoyalS/rawtoreel/actions/workflows/pipeline.yml/badge.svg)](https://github.com/ChandanaRoyalS/rawtoreel/actions/workflows/pipeline.yml)

Every push runs the whole pipeline on a synthetic clip in GitHub Actions. Open the latest run,
read the job summary to see what the cut removed, and download the finished videos from the
**Artifacts** section; no install needed to check that it works.

```
rawtoreel intake my-clip ~/Videos/raw.mp4 --title "How I built this"
rawtoreel run my-clip --format youtube --music
# -> outputs/my-clip.youtube.mp4
```

## The seven steps

Same steps, every job. Only steps 3 and 5 change with the output format.

| # | step | what it does | writes |
|---|------|--------------|--------|
| 1 | **intake** | copies the raw clip into `projects/<job>/raw/`; the original is never touched | `manifest.json` |
| 2 | **rough cut** | transcribes with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (word timestamps), removes filler words, long pauses, dead air and restarted sentences, polishes the voice | `transcript.json`, `cutlist.json`, `cut.mp4`, `script.md` |
| 3 | **graphics** | plans beats (title card, lower third, chapter pills) from the transcript, renders them with [HyperFrames](https://github.com/heygen-com/hyperframes) as a transparent layer | `graphics-plan.json`, `overlay.<fmt>.webm` |
| 4 | **second pass** | the human hook: write what to change in `notes.json`, re-run from here; only downstream steps recompute | re-cut if asked |
| 5 | **captions** | word-timed `.ass` captions with the spoken word highlighted; also an `.srt` for platform upload | `captions.<fmt>.ass`, `.srt` |
| 6 | **music** | optional: loops a bed to length and sidechain-ducks it under the voice | `music.wav` |
| 7 | **export** | composites cut + overlay + captions + music, fits the format, writes a report | `outputs/<job>.<fmt>.mp4`, `.json`, `.jpg` |

Each step's output is a plain file you can open, diff, or edit by hand before the next step runs.
`cutlist.json`, for example, lists every removal with a reason:

```json
{ "start": 3.38, "end": 4.82, "reason": "repeat", "text": "we are going to" }
{ "start": 9.04, "end": 10.13, "reason": "silence", "text": "1.3s pause" }
{ "start": 11.26, "end": 11.66, "reason": "filler", "text": "uh" }
```

## Formats

| preset | size | reframe | captions | graphics |
|--------|------|---------|----------|----------|
| `youtube` | 1920x1080 | letterbox | none (upload the `.srt`; platform captions beat burned-in ones) | glass title card + lower third + chapter pills |
| `reels` | 1080x1920 | blurred pad | centred, word highlight | top-half cards |
| `tiktok` | 1080x1920 | centre crop | low, under the face | hook card only |

Presets are JSON in `presets/formats/`. Copy one, change numbers, pass `--format <name>`.

## Install

Needs Python 3.10+, Node 22+, and ffmpeg on `PATH`.

```bash
git clone https://github.com/ChandanaRoyalS/rawtoreel && cd rawtoreel
pip install -e .          # python side: faster-whisper, typer
npm install               # node side: hyperframes, gsap
npx hyperframes browser ensure   # downloads a headless Chrome for rendering (once)
```

The first rough cut downloads the Whisper `small` model (~500 MB) into `~/.cache/huggingface`.
It runs on CPU at roughly real time; set `"model": "base"` in `presets/rough-cut.json` for faster,
rougher transcripts, or `"medium"` for better ones.

English-only clips can use NVIDIA's Parakeet-TDT instead (`pip install -e ".[parakeet]"`, then
`"engine": "parakeet"` in `presets/rough-cut.json`): about 8x faster than Whisper on CPU with
token-level timestamps, fetched once (~480 MB) from the sherpa-onnx GitHub release.

No footage handy? `pip install piper-tts && rawtoreel sample` generates a narrated test clip with
fillers, a restarted sentence and long pauses baked in; it is what CI runs on.

## Usage

```bash
rawtoreel intake <job> <clip> [--title "..."] [--speaker "..."] [--role "..."]
rawtoreel run <job> [--format youtube|reels|tiktok] [--music] [--from N] [--prune]
rawtoreel step <n> <job> [--format ...]      # one step, 2-7
rawtoreel status <job>
rawtoreel formats
```

A typical loop:

1. `rawtoreel intake talk raw.mp4 --title "Why I built an MCP gateway" --speaker Chandana`
2. `rawtoreel run talk` and watch `outputs/talk.youtube.mp4`
3. Write `projects/talk/notes.json` (below), then `rawtoreel run talk --from 4`
4. `rawtoreel step 3 talk -f reels && rawtoreel step 5 talk -f reels && rawtoreel step 7 talk -f reels`

### `notes.json` (step 4)

```json
{
  "extra_cuts": [[12.4, 13.9]],
  "restore":    [[30.0, 31.2]],
  "drop_beats": [2],
  "edit_beats": {"0": {"text": "A better title"}},
  "callouts":   [{"start": 8.0, "duration": 3.0, "text": "Link in description"}],
  "title": "Override the title",
  "speaker": "Chandana", "role": "AI engineer"
}
```

Times in `extra_cuts` and `restore` are seconds in the **raw** clip (look them up in `cutlist.json`).

### Style

`presets/style/default.json` holds colours, caption look and timings. `presets/caption-corrections.json`
fixes words the transcriber gets wrong (brand names, your name) before cutting and captioning.

## How the cut is decided

`rawtoreel/cutlist.py` is pure Python over the word list, so it is unit-tested without ffmpeg or a model:

- **filler**: a word in the filler list (`um`, `uh`, ...), padded by 60 ms
- **silence**: `ffmpeg silencedetect` spans over 0.7 s, shortened to a 0.25 s natural pause
- **repeat**: the same three or more words said again within 12 s; the *first* take is removed
  and the last one kept, which is almost always the one you meant; single-word stutters too
- **edges**: dead air before the first word and after the last

Removed spans are merged, the complement becomes the keep list, and `ffmpeg trim+concat` re-encodes
it so cuts land on exact frames. Word times are remapped onto the cut, so captions and graphics
never drift.

## Why HyperFrames for the graphics

A HyperFrames composition is an HTML file with timing attributes and one paused GSAP timeline,
rendered frame by frame in headless Chromium. The same `graphics-plan.json` always produces the same
pixels, the composition can be linted (`npx hyperframes lint projects/<job>/overlay-src/<fmt>`), and
the overlay renders as a transparent WebM that ffmpeg composites in one pass. That keeps the heavy
video work in ffmpeg (fast) and the design work in HTML/CSS (easy to change).

## Layout

```
rawtoreel/            python package
  cli.py              commands
  cutlist.py          cut decisions (pure, tested)
  transcribe.py       faster-whisper wrapper + corrections
  ffmpeg.py           probe / silence / trim+concat / fit filters
  steps/              intake, rough_cut, graphics, second_pass, captions, music, export
  render/             hyperframes.py (overlay HTML + render), captions.py (.ass builder)
presets/              formats/, style/, rough-cut.json, caption-corrections.json
music/                drop CC0 tracks here (see music/README.md)
projects/<job>/       working files per clip (git-ignored)
outputs/              finished videos (git-ignored)
tests/                pytest
.github/workflows/    the end-to-end run
```

## Limits

- Built for one speaker talking to camera. A clip with little or no speech (b-roll, an event, a
  montage) is detected and passed through uncut, with graphics and music still applied; nothing
  is tightened automatically in that case.
- "Repeat" detection sees repeated *words*; a purely visual retake with different wording is not caught.
- Vertical formats reframe the whole frame (crop or blurred pad); there is no face tracking yet.
- Overlay rendering is CPU-bound Chromium: expect roughly 20-40 s per minute of overlay on a laptop.

## License

MIT. HyperFrames is Apache-2.0, GSAP is used under its standard no-charge license, faster-whisper is MIT.
