# How to write a theme

A theme, or skin, is the table un's interactive surface renders with: one TOML file at `.un/themes/<name>.toml`, holding what the text IS rather than what it looks like. `tool_result = "dim"` and not `dim cyan` scattered through the renderer, which is what lets you restyle without touching code.

A skin decides four things: the colour of every role, the characters the boxes are drawn with, which optional screen elements are drawn at all, and how the conversation is spaced.

## The smallest working skin

```toml
# .un/themes/inkwell.toml
[roles]
user_text = "#c9d1d9"
tool = "bold #f0883e"
```

Name it in `.un/config.toml`:

```toml
theme = "inkwell"
```

Or for one run: `un chat --theme inkwell`.

Every key in every table is optional. un's built-in table is always the base and your file layers over it PER KEY, so a skin naming two roles is a skin with two overrides, not a table with twelve holes in it. Leave out `[glyphs]`, `[decorators]` and `[layout]` entirely and you get un's boxes, un's screen and un's spacing.

## Values

`[roles]` values are `rich` style strings: a colour name, a `#rrggbb`, or the attributes `bold`, `dim`, `italic`, `underline`, `reverse`, combined with spaces. `on <colour>` sets a background. `default` leaves the terminal's own foreground alone.

`code` is the exception. It is a pygments theme NAME, not a style - it colours fenced code blocks in the model's answers. Try `monokai`, `material`, `nord-darker`, `one-dark`, or `bw` for no highlighting at all.

## The roles

The whole set. Nothing else is read, and a key un does not know is carried but never painted.

| Role | What it paints |
|---|---|
| `assistant` | The model's own prose |
| `note` | What un says rather than the model: a slash result, a refusal, an advisory from a plugin |
| `bullet` | The mark in the gutter: the bullet on a line, the branch under a tool call |
| `tool` | The tool call line |
| `tool_result` | What that call returned |
| `user` | The `>` marker inside the input box, the marker alone |
| `user_text` | Your own text: what you type, and the line echoed back once you send it |
| `error` | A failure un is reporting to you |
| `interrupted` | A turn you ended yourself |
| `status` | The caption under the input box: model, tokens, elapsed |
| `time` | The clock in front of each conversation line, in your local time |
| `waiting` | The pulse shown while the model is answering |
| `border` | The banner and input-box rules |
| `banner_art` | Inside the welcome box: your `.un/banner.txt` art, or un's wordmark when there is none |
| `banner_text` | Inside the welcome box: the version, session id and project path lines |
| `pending` | A line committed with an Enter mid-turn, waiting above the box to run |
| `ask` | The choice modal the AskUser tool opens: its border and its text |
| `code` | Not a colour - the pygments theme for a fenced code block |

`user` and `user_text` are two roles rather than one so a skin can mark the input line without colouring the prose, or the other way round.

Prefer an explicit `#rrggbb` over `white`: `rich` reads `white` as ANSI colour 7, which many terminals paint with the same grey they paint `default`, so `user_text = "white"` can arrive indistinguishable from `assistant`.

## `[glyphs]` - the characters the screen is drawn with

Nine keys, the whole set, shown here at their built-in values. The first seven are rules: the same characters draw the welcome banner, the input frame and the choice modal, because they are one line to anyone looking at the screen. The last two are the marks in the conversation's gutter.

```toml
[glyphs]
top_left = "╭"
top_right = "╮"
bottom_left = "╰"
bottom_right = "╯"
horizontal = "─"
vertical = "│"
inner_divider = "─"
bullet = "⏺"
user = ">"
```

`inner_divider` is the fill for the rules `[decorators]` fences the conversation with. It ships as the same character `horizontal` does, so the built-in screen reads as one box, but it is its own key - set it alone and the dividers change while every box rule stays put.

`bullet` is the mark in front of a prose line - a reply, a tool call, an error, an interrupted turn - and the two info rows inside the welcome banner. `user` is the mark in front of what you typed: the echoed line in the conversation, the marker in the input box, and each line waiting in the queue while a turn runs. Which role paints a mark follows the line it sits on: `bullet` on a reply, a tool call and a tool result, `user` on an echoed line, `error` on an error, `interrupted` on an ended turn, and `banner_text` on the banner's two rows.

One mark is not here. `⎿`, in front of what a tool call returned, says "this came back from that" - that is grammar rather than decoration, so it is fixed and a skin only colours it, through `bullet`.

Merged per key like the roles: name `horizontal` alone and the other eight stay built-in. An ascii set suits a terminal whose font draws box characters at a mismatched weight:

```toml
[glyphs]
top_left = "+"
top_right = "+"
bottom_left = "+"
bottom_right = "+"
horizontal = "-"
vertical = "|"
inner_divider = "-"
```

### Glyphs longer than one character

Any glyph can be a string rather than a single character, and the boxes still close.

```toml
[glyphs]
top_left = "/*"
top_right = "*\\"
bottom_left = "\\*"
bottom_right = "*/"
horizontal = "-="
vertical = "|"
inner_divider = "~"
```

A glyph used as FILL - `horizontal` and `inner_divider` - is tiled to the exact width and cut wherever the width runs out, so `-=` across an odd span ends on a bare `-`. The rule always spans its whole width; one that stopped short would leave the box visibly open.

A glyph used as an EDGE - the four corners and `vertical` - takes as many columns as it has characters, and the fill between the edges gives up exactly that many. Every row of one box spans the same total, so the corners and the vertical do not have to be the same length: a two-column corner beside a one-column vertical still closes in the same column.

A long `vertical` is charged on every row, so it eats the room inside the box. Past a point the welcome banner will drop to its short mark because the wide one no longer fits.

A long `user` is charged the same way, and on the input row only: the marker is drawn between the left rule and what you are typing, so the room for typing is what gives way. A long `bullet` costs the conversation nothing but the column it occupies, and a body too narrow for its text wraps under itself rather than off the side.

The two gutter marks share ONE cell, as wide as the wider of them. That is what keeps a straight left edge down the conversation: set `bullet = "◆◆"` beside `user = ">"` and the `>` sits in a two-column cell with a blank after it, rather than starting its line one column left of every other. Emptying a mark is allowed and draws nothing, and the cell is still as wide as the mark you kept.

Past the point where a mark is wider than the whole row there is no room left to give, and the input row runs past the rules. The same is true of a long `vertical`. Nothing checks it; you see it on the first render.

Use single-WIDTH characters. A glyph the terminal renders two cells wide - CJK, emoji, a combining mark - pushes the closing edge out of the column the frame was measured for. un counts characters, not terminal cells, and does not check this: you see it on the first render and fix it by editing one string.

## `[decorators]` - elements the screen does not draw by default

Three keys, the whole set:

| Key | What it draws |
|---|---|
| `status_bar` | A pinned row above the conversation: un's version, the session id, the project root |
| `inner_divider` | A rule under the bar and another above the footer, fencing the conversation off from the decorators either side of it |
| `status_bar_text` | What the bar SAYS - see below. Not a role |

For `status_bar` and `inner_divider` the VALUE is the role the element is painted in, and assigning one is what ENABLES it. An empty value is that element off, which is the built-in screen and what every skin naming no `[decorators]` gets.

```toml
[decorators]
status_bar = "status"
inner_divider = "tool"
```

The divider rules are drawn from your `glyphs.inner_divider`, which is a key of its own - set it to change the dividers without touching any box rule.

Two things to know before turning them on. The decorators come out of the CONVERSATION's rows rather than the screen's, so the window shortens by exactly the rows drawn. And on a terminal too short for both, they come off WHOLE and the conversation keeps its rows - half a frame is not a frame.

The value must be a role that exists in the table, or a valid `rich` style. Unlike a bad role, it is not checked when the skin is loaded: an unknown word fails when the row is painted.

### `status_bar_text` - what the bar says

A format string over three fields, with any prose you like around them. Each field carries its own label, so a template is mostly placeholders.

| Field | Expands to |
|---|---|
| `{version}` | `un v1.2` - the number comes from the installed package|
| `{session}` | `session 01J8Z...` - the id of the conversation on screen, re-read after a `/resume` |
| `{project}` | The project root this session is running in |

```toml
[decorators]
status_bar = "status"
status_bar_text = " {version}  {session}  {project} "
# or, one of these at a time:
# status_bar_text = " ~ {project} ~   {session}   [ acme corp ]"
```

The first is what un draws when you name no `status_bar_text`. Between turns, before a session exists, `{session}` and `{project}` are empty. A field un does not know is drawn as you typed it - `{whoops}` appears in the bar as `{whoops}` - so a misspelling shows itself rather than disappearing. The row is cut to the terminal's width, so a long template loses its right-hand end.

## `[layout]` - how the conversation is spaced

One key, the whole set:

| Key | What it does |
|---|---|
| `condensed` | `false`, the default, puts a blank line before every entry but a tool result. `true` packs them tight |

```toml
[layout]
condensed = true
```

Under the default spacing a tool RESULT is the one thing that gets no line of its own: it stays against the call it came from, so the two read as one event. Everything else - a reply, your own line, a new tool call - starts after a blank. `condensed = true` is what un drew before this key existed: no line between entries at all.

It changes the on-screen session view only. A piped run - `un chat 'PROMPT' > out.txt` - is unspaced either way, because there is no screen to space.

Anything other than `true`, `1` or `yes` reads as `false`, so a typo gives you the default spacing rather than a finding.

## Additional glyphs

░
▒
▓
▚
▞
ᐁ
ᐃ
ᐊ
ᐅ
‗
∥
∎
⊐
⊓
⊔
⊏
⊕ 
⊖ 
⊗
⊢ 
⊣ 
⊤ 
⊥
⋀ 
⋁
⋂
⋃
⋮ 
⋯
←
↑
→
↓
↔
↕ 
↖ 
↗ 
↘ 
↙
⇇
⇈
⇉
⇊
╱
╲
╳
□
■
◀
▰
▱
▲
▶
▼
▫
◊
▨
◍
◐
◑
◒
◓
🭼 
🭽
🭾
🭿
🮜
🮝
🮞
🮟
🯰
🯱
🯲
🯳
🯴
🯵
🯶
🯷
🯸
🯹
𜸉
𜸊
❮
❯
🮨
🮩
🮪
🮫
🮬
🮭
🮮
═
║
╒
╓
╔
╕
╖
╗
╘
╙
╚
╛
╜
╝
╞
╟
╠
╡
╢
╣
╤
╥
╦
╧
╨
╩
╪
╫
╬
