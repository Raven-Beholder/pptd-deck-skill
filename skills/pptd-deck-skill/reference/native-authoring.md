# Current native workflow

Use this route for the current independent editor and supported source-only PPTX generation. Resolve paths from the skill directory. Python 3/PyYAML export uses no UI; layout QA also needs Pillow.

## Authoring boundaries

- Read `pptd.md` for the DSL. Native export strictly validates its supported subset and reports unknown fields; do not silently strip unsupported content or fall back to another backend.
- The stable QA primitives are text, `rect`/`ellipse`, straight two-point sharp lines, and local PNG/JPEG images with cover/contain/fill placement. Author diagrams from those primitives when computer use is prohibited. Crop evidence images before adding them; include their source next to the exhibit.
- Prefer a single multilingual font family. Existing independent `latin`/`ea` values are retained when opening old projects; the editor's unified font control writes one family for both scripts.
- Theme properties offer explicit edit/delete actions. Referenced theme entries cannot be deleted until their uses are removed. Changes have undo/redo and must be saved to the project.
- Text/rich-text source is collapsed by default. Ordinary text supports direct editing; formula-containing frames can be edited through source or the formula dialog.

## Editable formulas

Use inline `\( ... \)` inside plain text or rich-text paragraphs. Do not insert HTML tags inside a formula. Formula styling inherits size/color; Office uses Cambria Math. Plain-text YAML strings avoid escaping mistakes; in rich HTML, escape `<`/`>`/`&` when needed.

The shared native parser supports common Greek letters, relations/sets/arrows, common functions, `\text`/`\operatorname`, fractions, indexed roots, scripts, sums/products/multiple integrals, mathematical alphabets, `\left...\right`, binomial coefficients, accents/bars, over/undersets and `matrix`/`pmatrix`/`bmatrix`/`Bmatrix`/`vmatrix`/`Vmatrix`/`cases`/`aligned`/`gathered`. Matrix rows use `\\`; columns use `&`. Rows must have equal widths; cases has two columns. Arbitrary macros/environments and full TeX are not supported. Spacing is approximate across engines. The parser bounds source length to 10000 characters and recursive depth to 64.

Preflight every authored formula with the source parser before publishing:

```python
import sys
sys.path.insert(0, str(SKILL_DIR / 'scripts/local-export'))
from native_math import parse
parse(r'\mathrm{Attention}(Q,K,V)=\mathrm{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V')
```

## No-computer-use layout checks

Use the fixed prepare/review/export protocol in [pipeline.md](pipeline.md). `prepare` writes all numbered page PNGs and an overview, validates real font mappings and rejects missing glyphs, unsupported rendering features and overflow. Fix reported errors and re-run; review every individual page before recording a visual review. The standalone `render_native.py` remains available for debugging with `--fonts /abs/project/fonts.json`.

The renderer is a Pillow layout proof, not a screenshot of Office or the editor. Math typography is approximate (especially mathematical alphabets/accents and detailed matrix alignment). State that Office/WPS/Keynote rendering was not verified unless actually tested. When this renderer cannot represent a feature, author with supported primitives or report that exact limitation; do not bypass a user's ban on computer use.

## Export and delivery

Before export, tell the user how to preview or rework the project in the web PPTD editor; get the exact command from `pipeline.py editor-info`. This notice is not an approval gate. After saved edits, repeat prepare and review. Use `pipeline.py export` for validated production output; direct exporters are lower-level tools and do not enforce the pipeline's review gates.

Native output preserves editable text, native shapes and Office Math, and uses fade slide transitions by default. It records font names without embedding. Inspect the package for slide count, formulas, hyperlinks and transitions; ZIP validity alone does not prove application rendering. Deliver the PPTX plus the self-contained PPTD project, pages and media, and optionally the reviewed overview.
