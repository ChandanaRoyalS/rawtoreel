# music/

Drop background tracks here (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`). Step 6 picks one per job
(stable choice by job name, or `--track name.mp3`), loops it to length, and ducks it under the voice.

This repo ships **no third-party audio**. With the folder empty, step 6 synthesises a soft sine pad
on the fly, so the pipeline still runs end to end and there is nothing to license.

Where to get tracks you can legally commit to a public repo (CC0 / public domain, no attribution):

- Free Music Archive, filtered to the CC0 license: https://freemusicarchive.org/search?quickSearch=&license=CC0
- Musopen (public-domain classical recordings): https://musopen.org/music/
- Wikimedia Commons, CC0 audio: https://commons.wikimedia.org/wiki/Category:CC-Zero_audio

Avoid for a public repo: Pixabay Music, YouTube Audio Library, Epidemic/Artlist trials. They are
free to *use* in a video but their terms do not allow redistributing the files.

Add a `CREDITS.md` next to any track you commit, even for CC0, so the source is traceable.
