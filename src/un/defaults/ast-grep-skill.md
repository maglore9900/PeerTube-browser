---
name: ast-grep
description: Writing ast-grep rules for the AstGrep tool - structural code search over the syntax tree - to reach for before writing anything beyond a bare pattern, or when a rule matches nothing and it is not obvious why.
---
# Agent instructions:

## When to reach for it

`AstGrep` matches the syntax tree. `Grep` matches text. The question is whether what you
are looking for is a SHAPE or a STRING.

A shape: every call to `find_user`, however it is wrapped or line-broken, and not the same
characters sitting in a comment or a docstring. A string: a spelling, an error message, a
config key. `Grep` is faster and needs no language support, so use it unless the structure
is the point.

## The two forms

`AstGrep` takes exactly one of `pattern` or `rule`, plus a required `path`.

`pattern` is a single-node search and covers most of what you want:

    AstGrep(pattern="use($$$ARGS)", path="src")

`rule` is inline YAML, and is the only form that can ask about a node's CONTEXT - this
call, but only inside that function. Nothing in a pattern can reach a parent or a sibling.

    id: use-inside-a-function
    language: python
    rule:
      pattern: use($$$ARGS)
      inside:
        kind: function_definition
        stopBy: end

`lang` is optional; ast-grep infers it from file extensions.

If a bare pattern answers the question, use it. Reaching for `rule` when `pattern` would
do is the most common way to spend ten minutes on a one-line search.

## Metavariables

- `$NAME` captures exactly one node.
- `$$$NAME` captures any number, including none. Use it for argument lists and bodies.
- `$$NAME` captures one UNNAMED node, which you rarely want.
- `_NAME` matches without capturing.

A metavariable must be a whole node. `$N` will not match half an identifier, and
`foo_$N()` matches nothing.

## Escalate in this order

Stop at the first rung that answers the question.

1. `pattern` - a literal shape with metavariables. Most searches end here.
2. `kind` - match by node type when the shape varies but the construct does not:
   `function_definition`, `class_definition`, `call`, `decorator`. Get the name from a
   tree dump, never by guessing.
3. Relational - `inside`, `has`, `precedes`, `follows`. This is why `rule` exists.
4. Composite - `all`, `any`, `not`. Combine the above when one condition cannot express it.

These are what you nest INSIDE the relational and composite rules above, not a fifth
rung: `pattern`, `kind`, `regex` (matches the node's text), `nthChild` (positional) and
`range` (by line and column) go anywhere a rule is expected.

`field` narrows a rule to one labelled child - `field: name` on a `function_definition`
reaches the name and not the body.

## stopBy: end on every relational rule

This is the single most common reason a rule that looks right matches nothing.

A relational rule stops at the first node that does not match, so by default it only sees
the immediate neighbour. `stopBy: end` makes it traverse the whole subtree:

    has:
      pattern: await $EXPR
      stopBy: end

Write it by default. Leave it out only when you specifically mean the immediate parent or
child, and say so in the rule's `id`.

## When a rule matches nothing

Work down this list rather than editing the rule at random.

1. Dump the tree. `AstGrep` cannot do this - it has no flag passthrough - so run the
   binary with `Bash`:

       ast-grep run --pattern 'def lookup(s): pass' --lang python --debug-query=cst -- .

   The binary is `ast-grep`, never `sg`. On Linux `sg` is util-linux's setgid command,
   so typing it runs an unrelated program and prints something that looks like a broken
   search rather than an error. This is the only step here that types the binary name.

   `--debug-query` dumps the tree of the PATTERN, not of the files searched, so pass real
   code with NO metavariables. `$` and `$$$` are not valid syntax in any language, so a
   pattern containing them comes back full of `ERROR` nodes and tells you nothing. Read
   the `kind` names out of the dump.
2. Cut the rule down. Delete sub-rules until something matches, then add them back one at
   a time. The one that kills the match is the one that was wrong.
3. Add `stopBy: end` to any relational rule that lacks it.
4. Check the metavariable form. `$ARGS` matches one node; a call with two arguments needs
   `$$$ARGS`.
5. Check the language. An unsupported `lang` is an error, but an inferred one can be wrong
   for an unusual extension.
