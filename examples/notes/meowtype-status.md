---
title: meowtype — Voice Input App Status
aliases:
  - meowtype
  - voice input
  - macOS app
  - dictation
summary_points:
  - SwiftUI native, macOS-only
  - Mixed CN/JP/EN input mode
  - v0.1 internal testing
last_action: 2026-04-28 latency tuning on the recognition engine
status: active
author: cc
---

# meowtype — Voice Input App Status

## What it is

A native macOS voice-to-text input source. Mixed-language tolerance built in (CN/JP/EN can appear in the same utterance without forcing a language switch).

## Architecture

- SwiftUI front-end, `IMKInputController` for system-level dictation
- Whisper-small running locally for the recognition pass
- Custom punctuation post-processor that respects CJK conventions (no auto-period after Japanese clauses)

## Open questions

- Latency floor on the M1: still ~600ms end-to-end. Whisper-tiny would help but accuracy drops.
- App Store sandbox restrictions on accessing IME APIs — TBD.
