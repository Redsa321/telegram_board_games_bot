# Optimization Plan

## Completed Foundation

- Persist piece selection without editing the Telegram message
- Render only after a completed move
- Respect Telegram `RetryAfter` flood-control responses
- Keep SQLite on a durable path outside the repository

## Stage 1: Measure

Add structured timings for callback receipt, database reads/writes, robot calculation, board rendering, and Telegram message editing. Record request counts and p50/p95 latency without logging tokens or private game state.

## Stage 2: Reduce Telegram Requests

Coalesce obsolete board edits, prevent duplicate edits for unchanged state, and review wrong-turn and repeated-button behavior. Telegram API calls are the likely bottleneck and are subject to per-chat flood limits.

## Stage 3: Local Work

Profile robot calculations and combine related SQLite writes into transactions. Cache only immutable or safely invalidated values such as player display metadata.

## Stage 4: Hosting Transport

Measure network latency from the hosting laptop to Telegram. Consider webhooks only if incoming update delivery is materially slow; webhooks do not accelerate outgoing `editMessageText` requests. Keep polling if its measured latency is negligible.

## Stage 5: Rendering Platform

If inline-keyboard layout or interaction remains limiting, evaluate a Telegram Web App. It provides precise board dimensions and richer interaction but adds a web service and frontend deployment surface.
