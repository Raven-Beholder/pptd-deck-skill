# Deterministic generation helpers

Use the isolated environment described in SKILL.md. These commands do not open
a browser, download fonts or install software. Keep source and license notices.

## Automatic local fonts

For a new offline project, omit font paths:

```sh
python "$SKILL_DIR/scripts/pipeline.py" init --project "$PROJECT" --topic "数据库入门" --pages 12
```

The selector reads installed SFNT names, TTC face indices, regular/bold/italic
metadata and glyph coverage. It prefers a multilingual body font and a math
font. It writes actual paths and indices into `fonts.json`. Missing real styles
may use explicitly declared synthetic styles, disclosed by layout QA. It never
copies proprietary fonts into the project. This mapping is machine-local.
Selection covers the topic initially; `prepare` checks the complete authored text.

For an existing project without `fonts.json`:

```sh
python "$SKILL_DIR/scripts/pipeline.py" fonts-config "$PROJECT/deck.pptd"
```

`prepare` also creates a missing default config. Declared project fonts take
priority. Text and table styles, rich text and formulas inform the mapping.
Existing mappings and source `fontFamily` choices are preserved. If a declared
family is unavailable or lacks characters, the command reports a usable
replacement. Change that choice deliberately or add the requested project font.
Do not retry guessed file paths. No covering font means an explicit error.

Use `init --font-family ID` for portable OFL project fonts. That separate route
downloads verified resources on first use. Explicit installed `--body-font` and
`--math-font` options remain supported.

## Editable template starter pages

```sh
python "$SKILL_DIR/scripts/pipeline.py" template-samples --source "$TEMPLATE" --project "$NEW_PROJECT" --topic "Project presentation"
```

Use a new directory. This command preserves original PPTX/POTX bytes and extracts
layout evidence into `template/`. It creates a valid `deck.pptd`, `pages/`, local
PNG assets, automatic font mappings and `template-samples.json`.

Supported starter objects are explicit text runs, solid basic shapes and local
PNG/JPEG images. Bounds follow slide/layout/master placeholder inheritance.
Static layout/master objects are reused. Transparent image margins are trimmed
without changing their position. Source slide order and canvas size are retained.
Unavailable fonts are substituted for these new pages and listed in the report.

Read every `issues` entry and compare source and generated pages. Groups, tables,
charts, SmartArt, cropped images, complex fills/effects and complete inherited
text styling require reconstruction. Unsupported objects remain in the original
and evidence; they are not silently declared converted. The output is an editable
starting point, not a lossless import or a finished presentation. The number of
source slides does not constrain the final presentation length.

For a final template-based deliverable, continue with [template import and page
acceptance](template-import.md), including ordered reference images and explicit
page mapping. Do not label a starter extraction as visually accepted.

## Validate the actual exported content

Every native CLI, editor and pipeline PPTX export compares the staged OOXML to
the authored source before replacing or publishing a file. The audit checks:

- Element presence and text characters in source order.
- Formula counts without counting compatibility fallbacks twice.
- Effective font size, bold, italic and Latin/East Asian font family per character.
- Image, editable table and chart presence.

Dropped text/elements and style fallback are errors with a page and element ID.
Existing output survives a failed audit. `contentValidation` reports the checks
and per-page counts; pipeline reports store it under `packageValidation`.
Source pages with no elements are listed as `blankPages`, since a blank page
can be intentional. Image-only pages are valid. This audit cannot detect white
text on a white background, font substitution inside Office, or all visual
overlaps. Continue the normal prepare, truthful review and template comparison.
