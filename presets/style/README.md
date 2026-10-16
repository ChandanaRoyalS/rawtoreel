# Style presets

One JSON per look. `default.json` is a dark "glass" look with a coral accent and a warm
highlight colour for captions. Copy it to `mybrand.json`, change colours and timings, and run
with `--style mybrand`.

- `font_family` is used for burned-in captions (libass resolves it through fontconfig, so it must be
  installed on the machine that exports). The HyperFrames overlay uses the system sans-serif stack
  unless you vendor a font file and add an `@font-face` in `rawtoreel/render/hyperframes.py`.
- Timings are seconds: `title_in_s` (when the title card appears), `*_hold_s` (how long things stay).
