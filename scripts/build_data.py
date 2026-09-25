"""
One-off generator: reads substack-replies' replies.db and bakes today's
comment/like activity into data.js as sessions (bursts of activity per
person), in the spirit of first-replies' embedded `const data`.

Run locally, wherever replies.db lives:
    python3 scripts/build_data.py [YYYY-MM-DD] [path/to/replies.db]

Defaults to today and ../substack-replies/replies.db.
"""
import sys
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DATE = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).date().isoformat()
DB_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent.parent / "substack-replies" / "replies.db"
HANDLE = "alyssafuward"

# Reserved: Natalie Nicholson (user_id 354634571) always gets the guitar
# orange (index 1). Everyone else is hashed into the remaining 7 slots so
# nobody else collides with it. Keyed by user_id, not handle, since some
# people comment under more than one handle (same account, different name).
GUITAR_IDX = 1
PINNED = {354634571: GUITAR_IDX}
N_ORANGES = 8

REPLY_TYPES = (
    "note_reply", "post_reply", "comment_reply",
    "comment_mention", "community_comment_mention",
)
LIKE_TYPES = (
    "note_like", "post_like", "comment_like", "community_comment_like",
)
RESTACK_TYPES = ("restack", "restack_quote", "naked_restack_reaction")

SESSION_GAP_MINUTES = 25


def orange_for(uid):
    if uid in PINNED:
        return PINNED[uid]
    idx = int(hashlib.sha1(str(uid).encode()).hexdigest(), 16) % N_ORANGES
    if idx == GUITAR_IDX:
        idx = (idx + 1) % N_ORANGES
    return idx


def note_link(comment_id):
    return f"https://substack.com/@{HANDLE}/note/c-{comment_id}"


def comment_link(post_url, comment_id):
    if not post_url:
        return None
    if "/home/post/" in post_url:
        return post_url
    return f"{post_url.rstrip('/')}/comment/{comment_id}"


def thread_key(comment_id, post_id, ancestor_path):
    """Group post comments by the post itself (a post can have several
    separate top-level comment threads; they all belong in one room). Notes
    have no enclosing post, so group those by the root of the conversation
    (top of ancestor_path) instead."""
    if post_id:
        return f"post-{post_id}"
    if ancestor_path:
        return "t" + ancestor_path.split(".")[0]
    return "t" + str(comment_id)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur2 = conn.cursor()

    interactions = []  # flat list before grouping into sessions

    # Replies / mentions: comment_id points at the other person's actual comment.
    rows = cur.execute(
        f"""
        select ai.type, ai.comment_id, ai.created_at, ai.is_responded,
               c.handle, c.name, c.user_id, c.body, c.post_url, c.post_id, c.ancestor_path
        from activity_items ai
        join comments c on c.id = ai.comment_id
        where ai.type in {REPLY_TYPES} and date(ai.created_at) = ?
        """,
        (DATE,),
    ).fetchall()
    for r in rows:
        if not r["handle"]:
            continue
        link = comment_link(r["post_url"], r["comment_id"]) or note_link(r["comment_id"])
        interactions.append({
            "uid": r["user_id"],
            "handle": r["handle"],
            "name": r["name"],
            "category": "comment",
            "type": r["type"],
            "created_at": r["created_at"],
            "body": (r["body"] or "").strip(),
            "link": link,
            "responded": bool(r["is_responded"]),
            "thread": thread_key(r["comment_id"], r["post_id"], r["ancestor_path"]),
        })

    # Likes / restacks: only a target id + a capped list of recent senders.
    rows = cur.execute(
        f"""
        select type, raw_json, created_at
        from activity_items
        where type in {LIKE_TYPES + RESTACK_TYPES} and date(created_at) = ?
        """,
        (DATE,),
    ).fetchall()
    for r in rows:
        d = json.loads(r["raw_json"])
        target_comment_id = d.get("target_comment_id")
        target_post_id = d.get("target_post_id")

        link = None
        thread = None
        if target_comment_id:
            c = cur2.execute(
                "select post_url, post_id, ancestor_path from comments where id = ?", (target_comment_id,)
            ).fetchone()
            link = comment_link(c["post_url"], target_comment_id) if c and c["post_url"] else note_link(target_comment_id)
            thread = thread_key(target_comment_id, c["post_id"] if c else None, c["ancestor_path"] if c else None)
        elif target_post_id:
            p = cur2.execute(
                "select canonical_url from posts where id = ?", (target_post_id,)
            ).fetchone()
            link = p["canonical_url"] if p and p["canonical_url"] else f"https://{HANDLE}.substack.com"
            thread = f"post-{target_post_id}"
        else:
            link = f"https://{HANDLE}.substack.com"
            thread = "misc"

        category = "restack" if r["type"] in RESTACK_TYPES else "like"
        for uid in d.get("recent_sender_ids") or []:
            c = cur2.execute(
                "select handle, name from comments where user_id = ? limit 1", (uid,)
            ).fetchone()
            if not c:
                continue
            interactions.append({
                "uid": uid,
                "handle": c["handle"],
                "name": c["name"],
                "category": category,
                "type": r["type"],
                "created_at": r["created_at"],
                "body": "",
                "link": link,
                "responded": False,
                "thread": thread,
            })

    interactions.sort(key=lambda i: i["created_at"])

    # Group each person's interactions into sessions (bursts <= SESSION_GAP_MINUTES apart).
    # Keyed by user_id, not handle: a couple of people (e.g. Danielle Wright,
    # Ayushi) comment under more than one handle on the same account.
    by_uid = {}
    for i in interactions:
        by_uid.setdefault(i["uid"], []).append(i)

    sessions = []
    for uid, items in by_uid.items():
        items.sort(key=lambda i: i["created_at"])
        current = None
        for it in items:
            ts = datetime.fromisoformat(it["created_at"].replace("Z", "+00:00"))
            if current is None or (ts - current["_last_ts"]).total_seconds() > SESSION_GAP_MINUTES * 60:
                current = {
                    "uid": uid,
                    "handle": it["handle"],
                    "name": it["name"],
                    "orange": orange_for(uid),
                    "first_at": it["created_at"],
                    "items": [],
                    "_last_ts": ts,
                }
                sessions.append(current)
            current["items"].append({
                "category": it["category"],
                "type": it["type"],
                "body": it["body"],
                "link": it["link"],
                "responded": it["responded"],
                "thread": it["thread"],
            })
            current["_last_ts"] = ts

    for s in sessions:
        del s["_last_ts"]
        s["responded"] = any(i["responded"] for i in s["items"])

    sessions.sort(key=lambda s: s["first_at"])

    # Label each thread so a room isn't just an anonymous box: the article
    # title for post comments, or the opening note's own text otherwise. Note
    # text reads as first-person, so it needs a "by" attribution or a note
    # someone else wrote looks like it's coming from Alyssa (and vice versa).
    thread_keys = {it["thread"] for s in sessions for it in s["items"]}
    thread_labels = {}
    for key in thread_keys:
        label = "Conversation"
        by = None
        if key.startswith("t"):
            root_id = key[1:]
            row = cur2.execute(
                "select body, post_title, name from comments where id = ?", (root_id,)
            ).fetchone()
            if row and row["post_title"] and row["post_title"] != "Note":
                label = row["post_title"]
            elif row and row["body"]:
                label = row["body"].strip()
            if row and row["name"]:
                by = row["name"]
        elif key.startswith("post-"):
            post_id = key[len("post-"):]
            row = cur2.execute("select title from posts where id = ?", (post_id,)).fetchone()
            if row and row["title"]:
                label = row["title"]
            else:
                crow = cur2.execute(
                    "select post_title from comments where post_id = ? and post_title is not null limit 1",
                    (post_id,),
                ).fetchone()
                label = crow["post_title"] if crow and crow["post_title"] else "Post activity"
        elif key == "misc":
            label = "Other activity"
        thread_labels[key] = {"text": label, "by": by}

    out_path = Path(__file__).parent.parent / "data.js"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("const SESSIONS = ")
        json.dump(sessions, f, ensure_ascii=False, indent=1)
        f.write(";\nconst THREAD_LABELS = ")
        json.dump(thread_labels, f, ensure_ascii=False, indent=1)
        f.write(";\n")

    print(f"{len(sessions)} sessions, {len(interactions)} interactions -> {out_path}")


if __name__ == "__main__":
    main()
