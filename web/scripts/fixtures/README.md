# Browser media fixture

`readiness.webm` is a 160×90 VP8 WebM recorded from eight alternating solid-color
canvas frames at 12 fps using Playwright Chromium 1.64.1. It contains no user
content or external media. The readiness browser test uploads and plays this
same clip on every engine, including Linux WebKit where MediaRecorder is absent.

Recording support is not a requirement for Myink's video-background upload.
Playback, IndexedDB persistence, reduced-motion pause/resume, and URL cleanup
remain mandatory assertions.
