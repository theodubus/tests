@@SECTION_PROJET@@

## Socle: memory, documentation and tests

This repository uses the socle (version and fingerprint: `.socle/engine.lock`).
This file says **how** to work;
**where the project stands** is computed, and is never written by hand.

### At startup, and after every compaction

`python3 .socle/socle state` prints the derived state — commit, base, CI,
backlog, pending human requests —, then the active work and the canonical
memory. Under Claude Code, the `SessionStart` hook does it on its own; under
another agent, run it first. Nothing that is not in it is established.
What the human wrote themselves since the agent's last commit (an approval,
an answer in their terminal), the state lists: cite it to them in the next
reply, by its identifier and its link, since the command gave them a number
they cannot find in the conversation.

If the state was not injected when a Claude Code session started, the
agent's hooks are not loaded: the session started outside the project root.
Tell the human before any work, and push nothing; `socle state` also shows
it at the top, and the pre-commit hook then refuses the commit. Never write a
Claude Code setting yourself to restore the hooks.

An instruction from the human given in the conversation, that holds beyond
the turn (a rule, a preference, a prohibition), is written into the memory
before going on: in the active work if it concerns the work in progress,
otherwise in the journal, with its exact text. A compaction summary does not
always keep it, and a new session only has the memory.

### The memory, in `memory/`

| Layer | Where | Rule |
| --- | --- | --- |
| Canonical | `memory/canonical.md` | facts with status and proof; only changes with a new proof |
| Active | `memory/active.md` | work in progress, next steps; rewritten, kept short |
| Decisions | `memory/decisions/` | one ADR per file; only its status changes afterwards |
| Journal | `memory/journal/` | one dated entry per event; append only |
| Backlog | `@@BACKLOG@@` | topics with status and origin; closed with a reference |
| Requests | `memory/requests/` | human decisions in a queue, under the contract below |

An entry: `## F-NNNN — title`, then a line `> status : measured · proof : commit:<sha>`.
Statuses of a fact: `measured` (with `proof`), `assumed`, `refuted` (title struck
through, with `refutation`), `validated` (with `validation : D-NNNN`, written
after the human's answer). Full format: `@@MOTEUR@@/socle/FORMAT.md`.
An identifier is computed (`python3 .socle/socle new <type> "title"`), it is
never guessed. In case of conflict, the order of authority is: the code and
the tests, then the canonical memory, then the journal.

**Private memory**, if the policy chooses one (`[private] mode`): new content goes into the private zone, memory/private/, for the layers the policy makes private (`socle new` does it by default); an instruction from the human about a given entry is followed with `socle new … --private` or `--public`, and an existing public entry is moved with `socle private move <ID>`, whose public history keeps the old text: tell the human. Nothing private is copied to public, neither a `P…` identifier, nor its content, nor in a commit message, a pull request or a comment. In companion mode, a private change is committed in the private repository, then `socle private lock`. A new private name (an idea, a client) is added to the list of private terms (`socle private term <term>`); only the human removes one. If the policy requires a review before publication (`[private] review`), show the human what is leaving, then record their agreement with their exact text (`socle reviewed --relayed --by <name> --quote-file <file>`): at each push, or in batches. An encrypted private request cannot be read on GitHub: give it in full in the conversation. Unavailable (the state says so), nothing is concluded about what depends on it.

### Autonomy policy (`.socle/policy.toml`, changed by the human only)

1. **Loosening a guardrail** (`.socle/guardrails.toml`) requires an approved request; tightening is free.
2. **Deleting a test or changing an expected value** requires an approved request, or a specification the human changed themselves and that names the test; an ADR written by the agent is not enough.
3. **Design decision**: reversible and measurable, the agent decides and writes an ADR; costly to undo, ask.
4. **Irreversible or external action** (force-push, push to the default branch, publication, remote deletion, spending): always a request. The hook refuses it.
5. **Memory**: append only; "refuted" requires a measurement reference; "validated" is only written after the human's answer.
6. **Scope creep**: a neighbouring bug goes to the backlog, it is not fixed, unless it blocks.
7. **Repeated failure**: checks red after three attempts, stop and escalate with a request that sums up.
8. **Approval required**: queue the request, work on something else, never guess.

### Human decision requests

A request is read once the context is lost: it stands on its own.
`python3 .socle/socle new request "<decision>"` lays out the skeleton of the
eight fields: decision requested, context (the problem itself, summarised on
the spot, not a pointer), cited elements (each described in plain words,
never an identifier alone), where to look (a link to each document to read,
and what to check there), options (effort, risk, reversibility),
consequences (if the human approves, rejects, does not answer),
recommendation (verified kept apart from assumed), possible answers
including `insufficient-context`.
The lint refuses an incomplete request. The human answers in the
conversation; the agent records their answer, never choosing it, with the
exact text:
`python3 .socle/socle answer D-NNNN <answer> --relayed --by <name> --quote-file <file>`,
and copies it into the journal. An answered request is frozen. An answer is
only relayed to a request pushed as is: the human must have been able to
read it. A test whose expected value changes while waiting for such a
request, which names it, may stay changed in the tree at the end of the
turn; it is only committed after the answer.

### Reading the memory on demand

Startup only injects the state, the active work and the facts. The rest is
read when it is needed, without waiting to be asked:

- a cited identifier (`F-`, `B-`, `ADR-`, `D-`, `J-`) is read before relying
  on it: `python3 .socle/socle show <ID>`, which also gives its fingerprint;
- before a design decision, the decision index in the state says whether it
  has already been made: it is not reopened without a new fact;
- before opening a topic, the backlog (`socle show --index backlog`) says
  whether it already exists;
- to know why something is the way it is, search the journal
  (`grep -rn "<word>" memory/journal/`).

Reading is proven: a new decision, request or backlog topic cites what it
read with its fingerprint (`ADR-NNNN@xxxxxxxx`, `read : decisions@…`,
`read : backlog@…`). A stale or invented fingerprint is refused; the entry
must be read again. `socle new` puts in the index fingerprint.

### Before concluding

- `python3 .socle/socle verify --fast` passes (the `Stop` hook checks it); `verify` runs everything.
- If code changed, the memory did too: active work, journal, backlog.
- If code tied to a doc changed (`[[docmap]]` in the guardrails), the doc changes in the same work, or the commit that changes this code carries the trailer `Waive-doc: <reason>`, which covers that commit only.
- A fix (subject `fix:` or trailer `Fixes: B-NNNN`) delivers a test that fails on the parent commit.
- A public function added or changed is named by at least one test, or a commit waives it by name with its reason (`Waive-test: f, g — <reason>`). Existing code found without tests: the test is written right away if it is within the scope of the work, otherwise a topic goes to the backlog.
- An action only the human can take (refused by the hook, a service setting, a file they hold) goes to the backlog with `for : human`.
- **Every intervention that acted ends with a recap, then two lines**: `For you:` — what is up to the human, pending decisions and actions to take, or "nothing" —, and `Next:` — the proposed next step (next milestone, what remains before it), and what the agent is waiting for if it is waiting for something (a CI run, a match: what, and until when). The state computes what is up to the human; the `Stop` hook refuses to conclude without the two lines.
- **A file to read is given by its link**: the human reads in the conversation or on GitHub, not in the agent's container. `python3 .socle/socle url <path|ID>` gives the permalink, once the file is pushed; a pending request cited without its link, a relative link, or a path between backticks that does not exist in the repository make the end of turn refused. A path in another repository is written `repo:path`, the repository linked somewhere in the project by its address (failing that, declared in `[references] repos` of the guardrails); an unknown repository is reported.

### Never

- complete a head SHA, invent an identifier or a reference: the hook refuses them;
- write to a protected file (policy, adapter, engine lock, hooks, CI, human answers);
- answer on the human's behalf (`socle answer` without `--relayed` and a quote), or run `socle approve` or `socle private install`, which are for the human only;
- bypass a hook (`--no-verify`): the agent's hook refuses it on the project's repository, and the CI runs everything.

### What runs on its own

| Where | What |
| --- | --- |
| `.claude/settings.json` | Claude Code hooks: `SessionStart` (derived state), `PreToolUse` (refusals), `Stop` (end-of-turn checks) |
| `.socle/git-hooks/` | git hooks: `pre-commit` (fast checks), `prepare-commit-msg` (`Socle-Hooks`, `Socle-Hooks-Since-Commit` trailers), `commit-msg` (private memory leaks; a function with neither test nor waiver, a fix without a test, an agent commit without any agent hook, as warnings), `pre-push` (`verify --fast`, the pushed range judged as the CI will judge it, review before publication) |
| `.github/workflows/socle.yml` | CI: adapter capabilities, all checks against the base, socle self-test |
@@LIGNE_MUTATION@@
| `.git/socle/hooks.log` | local trace of every hook that fires, not versioned, shared by all worktrees of the repository |

List of checks: `python3 .socle/socle checks`.
