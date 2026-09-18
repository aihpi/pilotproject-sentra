# What we changed — my own notes

Notes to myself, in plain words, so I can explain this to people who do not
write software. Two parts: first the clean-up, then the evaluation system.

---

## Part 1 — The clean-up (refactoring)

**Where we started.** Nothing was broken. SENTRA worked: you asked a question,
it searched the documents, it wrote an answer with sources. The problem was
that it had been built quickly, and every new feature was getting more
expensive than the one before. That is what kills a pilot — not a bug, but the
day a small change takes a week.

It came down to three kinds of work.

**I made the system predictable.** Information used to travel through it as
loose bundles of values with no agreed form, so every part had to guess what it
was being handed. The same logic existed in several places in slightly
different versions, the settings file listed options that did nothing, and the
same failure could reach a user looking like three different errors. All of
that is now written down once, in one form, and the computer checks it.

**I broke up the pieces that were too big to touch.** The main screen was a
single 731-line file; the code had no clear layers, so anything could reach
anything. Now it is smaller parts with rules about what may depend on what —
and those rules are enforced automatically, not by memory.

**I put in a safety net.** Automatic formatting, type checking, and a test
suite that runs on every change. This is the boring one and it paid for all the
others: I can now change something and find out in two minutes whether I broke
anything.

**What I would tell a non-technical colleague:** we did not add features, we
made the thing maintainable. It does exactly what it did before — but it can
now be changed without fear, and it tells us when we get something wrong.
Everything since has been possible because of this.

**Left open on purpose:** one part of the document-processing machinery is
still written in a way I do not like. I wrote down why I left it and what
fixing it would cost. Better an honest note than a rushed fix.

---

## Part 2 — The evaluation system

**The question it answers.** How do we know SENTRA is any good? Not "does it
respond" — whether the answers are *right*, whether they cite the *correct*
source, and whether it says "I don't know" when it should. Before this, the only
way to answer was to ask somebody to try it and form an impression.

It follows the KISZ test procedure, so the process is not something I invented.
What we built is the system that runs it.

**How a round works.** Colleagues write down real questions, the answer they
expect and the source it comes from — always *before* SENTRA sees the question,
otherwise we would be marking our own homework. The system then asks SENTRA
every question several times, because a system that answers the same question
differently each time is itself a finding.

Everything that can be checked mechanically is: did it cite the right document,
or an outdated one; do the footnotes match the sources listed; was the answer
cut off; did the repeated attempts agree; and — for questions we know it cannot
answer — did it properly refuse instead of inventing something. A second AI
model, deliberately not the one under test, judges the things a fixed rule
cannot.

Then people take over. Anything suspicious goes to a reviewer, as does every
"trap" question, always, plus a random sample of the clean ones — otherwise we
would only ever check the cases the machine already doubted. The reviewer sees
the answer, the test case and the original PDF side by side and fills in the
assessment sheet the procedure requires. **The machine's verdict stays hidden
until they have submitted their own**, which is what makes the next part mean
anything.

**The number that matters** is how often the automatic check and the human
disagreed. That tells us how far the automation can be trusted. The two
directions are never averaged: the machine flagging something harmless costs us
time, the machine *missing* something is the one that matters.

**It is separate from SENTRA on purpose** — its own program, its own database,
talking to SENTRA the same way a browser does. If the thing measuring the
system shared parts with the system, it could agree with it for the wrong
reasons.

**What it found while I was building it.** This is what I would actually lead
with. Testing SENTRA turned up four real problems in SENTRA, including
re-processed documents leaving old fragments behind, still searchable. And
building the tests turned up problems in the tests: checks that passed while
measuring nothing.

The most instructive one: a "trap" question could not be entered into the
system at all, because the form insisted on a correct source — and a trap
question has none, by definition. So the most important check in the whole
procedure had never once run, while 197 tests passed over it.

**For collecting cases** there is now an Excel sheet and a Word form, so
colleagues can write cases without touching the system, and the system reads
the filled-in sheet directly.

---

## Where it stands

**Working and demonstrable today:** cases in, round runs, checks, review
screen, assessment sheets, the disagreement figure.

**The honest gap:** nobody from the WD has used it yet. The disagreement figure
only starts to mean something once real reviewers have worked real rounds.
Until then I have a working machine and no measurement.

**One decision that is not mine:** citations currently point at a section of a
document. The WD wants finer — a page. The tooling knows the page number and
our processing throws it away, so fixing it means re-processing the entire
document collection, which is hours of computing. Worth confirming "page, not
paragraph" before we start rather than after.

**Also underway:** a proper register of what the document collection actually
contains. We found 17 documents SENTRA can cite whose files no longer exist —
clicking the source gives an error. Nothing in the system could have noticed
that, which is why the register exists.
