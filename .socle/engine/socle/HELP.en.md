# The socle, on the human's side

The socle makes reliable the memory, the documentation and the tests of a
project that a coding agent maintains. The agent writes; automatic checks
catch its mistakes during its work, at commit time and in CI; you only
settle what no check can settle.

Commands run at the project root:
`python3 .socle/socle <command>`. This guide is shown by
`python3 .socle/socle help`.

## What you do

### 1. Install, update

```sh
PYTHONPATH=<clone of the socle>/engine python3 -m socle install --target . --owner @you --language en
```

The adapter (the project's language and its tools) is deduced from the
repository; `--adapter <name>` forces it. Options: `--private compagnon` or
`--private chiffre` (a private memory; companion mode is the safest,
encrypted mode depends on a filter such as git-crypt that the socle does not
install, and it is the least proven), `--review lots` or
`--review chaque-push` (review what leaves before publication),
`--language en` (a memory, templates and engine messages in English),
`--adoption` (an existing project some checks fail on: they become
warnings, and can only tighten).

The command ends with "What now": your next steps, in order, each with its
command. An update runs the same command again from the up-to-date clone of
the socle.

In companion mode, the private memory lives in a second, private repository.
Create it empty on GitHub, then:

```sh
python3 .socle/socle private install --repo <address of the private repository>
```

It clones it, makes the first commit there, writes the lock and creates a
deploy key; it ends with the two steps left on GitHub (the key as a deploy
key of the private repository, two secrets in the public repository), with
the link of each page.

After the first push, protect the default branch on GitHub: in the
repository settings, "Rules", a ruleset that requires the socle's CI
("Socle — verify, contrôles, auto-test") and the code owners' review before
any merge. Without it, a red CI does not prevent merging. `socle state` says
whether the CI is required, and reminds you otherwise.

### 2. Describe the project

```sh
python3 .socle/socle init --brief <document> --repo
```

The document is archived as is; `--repo` records what the repository already
contains (tools, tests, CI). The agent then asks you a few starting
questions, each with its default.

### 3. Answer the agent's requests

When a decision falls to you (loosening a guardrail, changing the expected
value of a test, a decision costly to undo, an irreversible action), the
agent writes a request that stands on its own, and gives you its link. You
answer in the conversation, with one of the possible answers written at its
end; the agent records your answer with your exact text.
`insufficient-context` sends it back to the agent, who rewrites it.

On your own, in your terminal:
`python3 .socle/socle answer D-NNNN <answer> --text "<your text>"`.

### 4. Approve your own protected changes

The policy, the guardrails, the adapter, the hooks, the CI and the engine
are protected: changing them without approval fails the commit. When you
are the one changing them (a socle update, your policy):

```sh
python3 .socle/socle approve --text "<reason>"
```

lists the changed protected files, then approves them on confirmation, by
writing an approved request (D-NNNN) to commit with them. The agent cannot
run this command; it will cite that number to you on its next turn.

### 5. Review before publication, if you chose it

With `review` in the `[private]` section of the policy, nothing leaves for
the public repository without your agreement: the agent shows you what is
leaving, and you answer in the conversation. On your own, in your terminal:
`python3 .socle/socle reviewed --by <you>`.

### 6. Commit yourself

The same checks apply to your commits. A public function added or changed is
named by a test, or waived in the commit message,
`Waive-test: f — <reason>`: the hook warns you at commit time, the CI
refuses without it. A fix (subject `fix:`, or trailer `Fixes: B-NNNN`)
brings a test that fails on the parent commit.

## What you read

- `python3 .socle/socle state`: where the project stands, computed every
  time, never copied: commit, CI, backlog, pending requests, and what falls
  to you.
- The end of each intervention of the agent that acted: "For you:", what
  falls to you, then "Next:", what comes next.
- The memory, in `memory/`: the facts and their proof, the active work, the
  decisions, the journal, the backlog, the requests.

## What depends on you alone

- The autonomy policy, `.socle/policy.toml`: what the agent decides alone,
  and what it asks you.
- Loosening a guardrail, in `.socle/guardrails.toml`; tightening is free,
  for the agent too.
- Irreversible or external actions: pushing to the default branch,
  publishing, deleting remotely, spending. The hook refuses them to the
  agent; it puts them in the backlog with `for : human`, and the state lists
  them for you.
