# substack-engagement-room

A prototype visualization: oranges walk into a room, drop a comment/like as a
speech bubble, then leave; a "Thread Rooms" panel groups the same activity by
Substack conversation.

## Workflow

- Straight to `main`, no PR — this is Alyssa's prototype/personal-project
  pattern (like kayvas-typing-game, avas-zoo-game), not the branch+PR flow.
- **Commit each meaningful change separately**, with a descriptive message.
  Alyssa tracks versions here to write up the build process later — `history.html`
  renders the commit log live from GitHub, so a batched "various fixes" commit
  is a blank spot in that record. One commit per user-visible change.
- Regenerate `data.js` via `scripts/build_data.py` after any changes to it —
  see the script's own docstring for date-range / `--since`/`--until` usage.

## Key files

| File | Purpose |
|------|---------|
| `index.html` | The room + thread panels; all rendering/animation logic |
| `history.html` | Version history, fetched live from the GitHub commits API |
| `scripts/build_data.py` | Reads `../substack-replies/replies.db`, writes `data.js` |
| `assets/oranges.js` | The 8 orange mascot variants (shared with alyssafuward-substack/first-replies) |
| `data.js` | Generated — baked session/thread data, not hand-edited |
