"""Build an adversarial style corpus: six invented operators, none of them the author.

WHY THIS EXISTS. The human/agent thresholds in `corpuslens/authorship.py` were
derived from one operator's own corpus, where human turns ran 3-27 words and
dispatched-agent prompts ran 453-686. Perfect separation — and possibly an
artifact of one person's unusually terse prompting style rather than a general
property of people.

So this corpus is written to BREAK that. Every persona here is a plausible way a
human might prompt that the word-count evidence would misread. The reverse case
is included too: a machine that dispatches tersely, which the same evidence would
call human.

WHAT IT CAN AND CANNOT TELL YOU. A synthetic corpus can FALSIFY a classifier —
if it calls a rambling human an agent, that is a real defect, because people like
this exist. It CANNOT validate one: passing here says nothing about the true
error rate on real people, because everyone in it was imagined by the same author
whose blind spots the test is meant to expose. It is a falsifier, not a
validator, and the honest use is to run `corpuslens label` on a real corpus for
an actual error rate.

GROUND TRUTH is recorded per turn in truth.json — the one thing a synthetic
corpus has that a real one does not.
"""
import json, pathlib, hashlib

OUT = pathlib.Path(__file__).parent

# (persona, true_author, [turns]) — true_author is the ground truth, never in the corpus
PERSONAS = [
    ("rambler", "human", [
        "ok so I've been staring at this for like an hour and I think the problem is somewhere in how we're handling the session boundaries but honestly I'm not sure, it might also be the timezone thing from last week coming back? Anyway what I want to do is go through it piece by piece, starting with the part where the file gets opened, because that's where it felt weird when I was reading it earlier today. I don't need you to fix anything yet, I just want to understand what's actually happening before we change it, because last time we changed something before understanding it and that cost us two days.",
        "right, that makes sense, but hold on — if that's true then why did the earlier run work? Unless it didn't actually work and we just didn't notice because the output looked plausible. Which, now that I say it out loud, is probably what happened. Can you check whether the earlier run was actually correct or whether we just assumed it was, I have a bad feeling about this and I'd rather find out now than after we ship it to anyone.",
        "yeah ok. do that.",
        "I'm going to be honest I don't fully follow the second half of that explanation. Can you go back over the bit about why the counter resets, but slower, and assume I've forgotten everything we discussed about the caching layer, because I have. It's been a long week and I'd rather ask a stupid question now than nod along and get it wrong later when I'm explaining it to someone else.",
        "that's much clearer, thank you. let's do it that way",
    ]),
    ("spec_writer", "human", [
        "New requirement. Please implement the following, in order:\n1. Add a configuration flag that controls whether the parser runs in strict mode.\n2. When strict mode is on, an unrecognised field should raise rather than warn.\n3. When it is off, preserve today's behaviour exactly — I do not want existing callers to change behaviour by accident.\n4. Add tests for both paths, including one that asserts the default is off.\n5. Update the docstring on the parser entry point to describe the flag.\nAcceptance criteria: the existing test suite passes unchanged, and the new flag is documented where a reader will actually look for it. Do not refactor anything outside the parser module while you are in there.",
        "Two changes to the above:\n- The flag should be readable from an environment variable as well, with the explicit argument winning when both are set.\n- Rename it to `strict_fields`, since `strict` on its own is ambiguous next to the other strictness setting we already have in the validator.\nEverything else stands.",
        "Approved. Ship it.",
        "One more, related. The error message raised in strict mode should name the field and the file it came from, because the current message says only that something was unrecognised and that is useless in a log. Keep it to one line. Do not include the field's value in the message — some of these carry credentials and they should not end up in logs.",
    ]),
    ("paster", "human", [
        "getting this, any ideas?\n```\nTraceback (most recent call last):\n  File \"app/loader.py\", line 212, in resolve\n    return self._cache[key]\nKeyError: 'session_id'\n```",
        "here's the function\n```python\ndef resolve(self, key):\n    return self._cache[key]\n```\nit used to have a default and I think someone removed it",
        "yep that was it. thanks",
        "different one now\n```\nValueError: invalid literal for int() with base 10: ''\n```\nhappens on about 1 in 200 rows, the rest are fine",
    ]),
    ("questioner", "human", [
        "what does the guard actually protect against?",
        "and what happens if the config is missing entirely?",
        "does that fail open or closed?",
        "ok so if I delete the file it denies everything? is that tested anywhere",
        "what about the postgres path, same thing?",
        "good. and who can change that file",
    ]),
    ("second_language", "human", [
        "Hello. I have question about the adapter. In my country we use different date format, and I am not sure if the tool can read it. Is it possible to configure, or must I change my data first? I prefer not to change the data because it is original and I want to keep it as it is.",
        "Thank you. I understand now. So the tool will drop these rows and tell me how many, this is acceptable for me. But I want to ask, is the number of dropped rows shown before or after the analysis? Because if after, I have already read the report and maybe I trust it too much.",
        "Very good. This is clear.",
        "One more question please. If I have two files with same session, will it join them or count as two sessions? In my case the tool was restarted in the middle of the work and I think it made two files.",
    ]),
    # THE REVERSE CASE: a machine that dispatches tersely. Word count says human.
    ("terse_dispatcher", "agent", [
        "Run the test suite and report failures.",
        "Fix the failing assertion in test_parser.py.",
        "Now run the linter.",
        "Commit with message: fix parser assertion.",
        "Check CI status.",
        "Report when green.",
    ]),
]

def main():
    base = "2026-03-0"
    events, truth = [], []
    for di, (persona, author, turns) in enumerate(PERSONAS, start=1):
        d = f"{base}{di}"
        sess = OUT / persona
        sess.mkdir(exist_ok=True)
        lines = []
        for ti, text in enumerate(turns):
            ts = f"{d}T{9 + ti:02d}:{(ti * 17) % 60:02d}:00Z"
            ref = hashlib.sha256(f"{persona}:{ti}".encode()).hexdigest()[:16]
            lines.append(json.dumps({"type": "user", "timestamp": ts,
                                     "message": {"content": [{"type": "text", "text": text}]}}))
            truth.append({"persona": persona, "turn": ti, "true_author": author, "ref": ref})
            lines.append(json.dumps({"type": "assistant", "timestamp": f"{d}T{9 + ti:02d}:{((ti * 17) % 60) + 2:02d}:00Z",
                                     "message": {"content": [{"type": "text", "text":
                                        "Understood. Here is what I found, and what I would do next."}]}}))
        (sess / "session.jsonl").write_text("\n".join(lines) + "\n")
    (OUT / "truth.json").write_text(json.dumps(
        {"note": "ground truth per turn; deliberately NOT in the corpus itself",
         "turns": truth}, indent=2) + "\n")
    print(f"built {len(PERSONAS)} personas, {len(truth)} operator turns")

if __name__ == "__main__":
    main()
