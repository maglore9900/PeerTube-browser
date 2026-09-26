<!--
EXAMPLE:
---
name: researcher
description: Searches the codebase and reports what it found. Read-only.
tools: Read, Grep, Glob
provider: ollama
model: qwen3
effort: low
max_turns: 20
---
You are a research agent working inside one repository.

Read widely before answering. Report what you found and where you found it, with file
paths and line numbers. Edit nothing, and do not propose edits unless asked.

When you cannot answer from the code, say so and name what you looked at. A guess that
reads like a finding is worse than an admission.

=============================================================================
HOW TO USE THIS TEMPLATE

Copy it to `.un/agents/<anything>.md` and edit it. The filename carries nothing -
discovery recurses and files the agent under its frontmatter `name`, so
`.un/agents/research/r.md` defines `researcher` and directories are yours to arrange.

Then activate it in `.un/config.toml`, which is a SECOND and separate step:

    [agents.researcher]
    enable = true

The file being present makes the agent KNOWN; the table turns it ON. `enable` is the only
key that table takes. `un agents` lists what is enabled, what is present and off, and what
was refused with the reason.

Delete this comment block when you copy the file. The body of an agent file IS its system prompt.

=============================================================================
THE FRONTMATTER

REQUIRED
  name          Lowercase letters, digits and hyphens only. It becomes the forked
                session's id suffix and so its transcript filename, which is why it is
                confined. Two files claiming one name: the second is refused and told
                which file already holds it.
  description   What the MAIN agent reads when it chooses between subagents. It is copied
                into the `Task` tool's own description, so write it as the answer to "when
                should I delegate to this one" - not as a title. This is the field that
                decides whether your agent is ever used.
  the body      Everything below the closing `---`. It IS the system prompt. An empty body
                is refused.

OPTIONAL
  tools         What the subagent may call, and nothing else: omitted means no tools. A
                single name may be written bare: `tools: Read`. Listing `Task` lets it
                delegate in turn, down to [agents].max_task_depth (default 3); the agent
                at that depth is not given `Task`. `Task(a, b)` limits it to the agents
                named. Tool availability is resolved at spawn rather than at
                discovery, so naming a drop-in tool works; `un agents` reports any name no
                plugin registered.
                `Tool(x, ...)` grants a tool AND scopes it for this agent: `Skill(wiki)`,
                `Read(docs, notes/**)`, `Bash(ls)`, `Bash(pytest:-x)`. Skill, SkillManage,
                Recall, Workflow and Task take names; Read, Write, Edit, Glob, Grep and AstGrep
                take path globs; Bash takes ONE program spec per entry. A call outside the
                scope is denied; one inside still meets the permission table.
  provider      A [providers.<name>] profile to serve this agent in place of the one main
                is on. Checked at discovery: a name matching no profile refuses the file.
                An empty value reads as absent, so the parent's endpoint stands.
  model         Sent to that provider in place of the profile's own model.
  effort        How hard THIS agent thinks. Checked against the same set `--effort` takes;
                a value outside it refuses the file. Omit to inherit.
  max_turns     How many provider calls the child may make with no human
                interaction between them. Omit for the one the profile above
                names, or the session's own where it names none. A child of an
                interactive session is attended, so its own AskUser extends its
                bound; a child of a piped or one-shot run is headless and the
                number is an absolute ceiling.

Any other key is refused by name.

=============================================================================
PROVIDER AND MODEL

Independent, and the three useful arrangements:

  provider only   Runs on that endpoint's own default model.
  model only      Runs on the main agent's endpoint, with a different model.
  both            Points one endpoint at a named model. This is how two agents share an
                  endpoint while one runs cheap and one runs expensive.

Neither is required. An agent declaring no provider and no model runs on whatever the main
agent is using, which is the right default for most agents - reach for these keys when you
want this agent on something OTHER than the main one.

-->
