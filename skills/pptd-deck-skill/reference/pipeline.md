# Native production pipeline

## Setup and authoring

Set `SKILL_DIR` to the directory containing SKILL.md and `PROJECT` to an absolute project folder. Use the isolated Python environment selected at installation. For a source checkout, run `uv sync --locked --python 3.12`, then prefix the commands below with `uv run --locked --project /absolute/repository`. The scripts never open a browser. Reuse the same interpreter across stages.

For a portable project, choose verified OFL resources from [fonts.md](fonts.md). A machine preset is available for wine-red-data, derived from its design.md:

```sh
python "$SKILL_DIR/scripts/pipeline.py" init --project "$PROJECT" --theme wine-red-data --topic "数据库入门" --pages 12 --font-family source-han-sans --extra-font jetbrains-mono
```

`--font-family` selects the body by catalog ID. Repeat `--extra-font` for additional families. STIX Two Math is added by default; `--math-family` selects a catalog MATH family explicitly. Downloads use pinned official bytes and hashes. Full fonts and notices live in `fonts/`, are declared in `customFonts`, and use relative `fonts.json` mappings. After download, generation and editing work offline. Regular/bold/italic mappings reflect the available real faces. Avoid combining these options with installed font options.

For an installed-font workflow, find local font files (macOS `/System/Library/Fonts`, Linux `/usr/share/fonts`, Windows `%WINDIR%/Fonts`). Use one multilingual body family for Chinese and Latin. Font names must correspond to the mapped files:

```sh
python3 "$SKILL_DIR/scripts/pipeline.py" init --project "$PROJECT" --theme wine-red-data --topic "Attention Is All You Need" --pages 18 --research --body-font "/absolute/installed/body.ttf" --math-font "/absolute/installed/math.otf" --family "Actual Font Family"
```

`init` creates deck.pptd, pages, media, fonts.json, theme.json, brief.json and evidence.json; it refuses to overwrite a nonempty project. Fill all TODO content. Existing projects skip init: add fonts.json and research evidence directly. Other themes use their design.md and manually authored manifest/theme. Do not fabricate an unsupported preset.

`fonts.json` maps real font files for each declared family and math. Paths may be absolute installed paths or relative to the configuration file. Optional `bold`, `italic`, `boldItalic` entries can select real faces. If synthetic styles are acceptable, set `syntheticStyles: true`; the report discloses the approximation. A TTC descriptor uses `{"path":"font.ttc","index":0}`. Example:

```json
{"families":{"Actual Font Family":{"regular":"/absolute/body.ttf","syntheticStyles":true}},"math":{"regular":"/absolute/math.otf","italic":"/absolute/math-italic.otf","syntheticStyles":true}}
```

Local installed mappings alone do not bundle fonts into the delivered project. On another machine, remap them and rerun checks. Declared project fonts and notices travel with project copies and ZIPs; a self-contained relative `fonts.json` travels too. Use `export --embed-fonts` to embed used project families in PPTX. Missing used families/styles or restricted embedding rights stop export. Missing glyphs are errors, not silent font fallback.

## Source evidence

Research decks set `brief.json` `requiresSources` to true. Maintain evidence.json alongside the pages. Source URLs and locations must identify primary evidence. Pin local source bytes with sha256 when available:

```json
{
  "sources":[{"id":"paper","url":"https://arxiv.org/abs/1706.03762","localPath":"sources/paper.pdf","sha256":"ACTUAL_SHA256"}],
  "claims":[
    {"id":"big","source":"paper","page":13,"location":"Table 2","value":28.4,"unit":"BLEU","dataset":"WMT14 English-German","split":"newstest2014"},
    {"id":"baseline","source":"paper","page":13,"location":"Table 2, previous best","value":26.36,"unit":"BLEU","dataset":"WMT14 English-German","split":"newstest2014"}
  ],
  "comparisons":[{"left":"big","right":"baseline","operation":"subtract","result":2.04}]
}
```

Every substantive or quantitative slide claim should have a source record and source footnote. Numeric comparisons need matching unit, dataset and split; record other relevant experimental context as well. Scripts check references, hashes and subtraction, but cannot prove that a claim accurately paraphrases the paper. The model must read and verify it. Do not compare a number to an unrelated baseline merely because units match.

## Fixed commands and gates

```sh
python3 "$SKILL_DIR/scripts/pipeline.py" prepare "$PROJECT/deck.pptd"
# Read .pipeline/render.json; inspect every .pipeline/images/NN.png.
python3 "$SKILL_DIR/scripts/pipeline.py" review "$PROJECT/deck.pptd" --mode visual --note "Describe actual full-deck inspection and remaining approximations"
python3 "$SKILL_DIR/scripts/pipeline.py" editor-info "$PROJECT/deck.pptd"
# Tell the user about web-editor preview/rework, with the command returned above.
python3 "$SKILL_DIR/scripts/pipeline.py" export "$PROJECT/deck.pptd" --output "$PROJECT/deck.pptx"
```

`prepare` validates export semantics before rendering and returns the editor command with its pre-export notice. `review` also reminds the model to give that notice. The scripts do not send chat messages themselves: the model must communicate it. Do not require another user confirmation for an already authorized export.

The editor command starts a local HTTP service. Share its printed URL; open/control it only when authorized. User changes saved through the editor require another prepare, page inspection, review and export. An editor preview cannot replace validation of the eventual PPTX file. Retain the editable project for future rework.

`.pipeline/` stores preflight, per-page images, render/review/export reports and repair backups. Input and code hashes prevent export after source, font, asset, tool or inspection-image changes. Export stages and validates ZIP/XML, relationships, page count and transitions, then publishes atomically. Existing PPTX is preserved unless an authorized replacement uses `--force`. Default transitions are fade; `--transition none` honors an explicit request.

## Repair loop: continue working after an error

Exit code 2 and `status: needs_repair` mean the task is still incomplete. Read `error` and `.pipeline/issues.json` before acting.

1. Identify the reported page, element, font or source path. Inspect that input and the failed stage.
2. If render errors include text-height overflow, run:
   `python3 "$SKILL_DIR/scripts/pipeline.py" repair "$PROJECT/deck.pptd" --apply`
   This only extends a text box into available space, preserves a backup and records changes. It never edits the factual text or shrinks font size automatically.
3. For remaining errors, repair the underlying cause: correct missing resource paths, map a suitable installed font, replace an unsupported glyph with equivalent notation, reflow/split text, or author supported primitives. Check that a changed formula retains its meaning. Do not blindly retry identical commands.
4. Rerun prepare and inspect changed pages plus the complete deck. Record review again, then export.
5. If the same error persists after two attempted fixes, inspect the responsible script/input and broaden diagnosis. Continue independent work. Ask for information only when the resource or decision is actually unavailable. Preserve source and prior outputs; report the exact blocker and resumable command if completion truly requires external input.

A failed visual review is recorded with `review --failed --note "Specific issues"`; repair and rerun rather than passing it. Stale repair reports cannot be applied.

## Honest capability fallback

Pillow supports basic text, editable formula AST approximations, solid rect/ellipse, straight two-point lines with a triangular end arrow, and local images with cover/contain/fill. Unsupported rotations, crops, complex elements/decorations and animations fail explicitly. Native export supports a broader subset; report that exact capability gap; this release has no legacy fallback.

Only when image inspection or required rendering capability is genuinely unavailable:

```sh
python3 "$SKILL_DIR/scripts/pipeline.py" prepare "$PROJECT/deck.pptd" --structural-only --reason "Specific missing capability"
python3 "$SKILL_DIR/scripts/pipeline.py" review "$PROJECT/deck.pptd" --mode structural --reason "Specific missing capability" --note "Describe source and structural checks actually performed"
```

Disclose the absence of visual QA and provide the web editor for user review. Structural mode still enforces source, manifest and native export validation. Never use it to conceal fixable layout, source or font errors. Pillow math spacing and synthetic styles remain approximate; Office/WPS/Keynote playback verification is a separate check and must not be claimed from these reports.
