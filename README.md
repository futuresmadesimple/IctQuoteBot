# X Post-Only Bot (12/day)

Posts prewritten tweets from `tweets.txt` only. No replies.

- 12 random ET times/day between 07:00–22:00
- 30-minute posting window
- Deletes the posted block from `tweets.txt` (or deletes duplicate content block)
- Commits/pushes `tweets.txt` and `.post_state.json` after each run
