# Template import, layout extraction and page acceptance

Use this route when the user supplies a PPTX or POTX as a design template. It imports
reference evidence. It does not convert arbitrary Office objects into editable PPTD.
Keep the original and reconstruct editable pages from the extracted layout and images.
No browser, Office installation, new dependency or network access is required by the importer.

## 1. Prepare source references

Create or open a PPTD project. Obtain one PNG or JPEG for **every** source slide,
including hidden slides, in presentation order. Export these images from the user's
chosen presentation application. Record the application and version when known.
The importer cannot render PPTX or establish that submitted images match its source.
Inspect their correspondence before import. Do not use newly generated candidate
images as the template reference in real acceptance work.

Write `references.json` next to the images. Paths are relative to that file and must
stay inside its directory. Use an explicit list; filenames are never sorted to infer
page order. Do not substitute an overview/contact sheet for page images.

```json
{
  "renderer": "PowerPoint; record the actual version and export date here",
  "pages": ["images/slide-1.png", "images/slide-2.png"]
}
```

The example renderer string is a placeholder for provenance, not proof of Office
verification. Each reference must have the template's aspect ratio (within 1%).
Images are limited to 20 million pixels. Each imported file is limited to 20 MiB;
the reference bundle is limited to 100 MiB. The editor's complete portable project
also has a 100 MiB limit, including pages and fonts. Reduce image resolution when needed.
ZIP processing allows at most 4096 entries and 100 MiB uncompressed; XML parts are
limited to 8 MiB. External relationships are never fetched. Unsafe paths, duplicate
entries, DTDs, missing parts and invalid relationships fail explicitly.

A POTX without sample slides cannot supply a page baseline. Add sample slides using
the required layouts and export their images first. Legacy `.ppt` files need conversion
in a presentation application before this workflow.

## 2. Import and extract

Run with the isolated environment described in [pipeline.md](pipeline.md).

```sh
python "$SKILL_DIR/scripts/pipeline.py" template-import "$PROJECT/deck.pptd" --source /path/to/template.pptx --references /path/to/references.json
```

Equal page counts default to a one-to-one mapping. Otherwise provide `--mapping
/path/to/mapping.json`. Every project page must appear exactly once, in manifest order.
Multiple candidate pages may use the same template page:

```json
[
  {"page": "pages/01.page", "sourcePage": 1},
  {"page": "pages/02.page", "sourcePage": 2},
  {"page": "pages/03.page", "sourcePage": 2}
]
```

Import publishes `template.json` and a project-local `template/<id>/` bundle after
validation. It preserves original PPTX/POTX bytes, submitted image bytes, normalized
reference PNGs and `layouts.json`. Every file has a SHA-256 digest. Existing templates
are not overwritten. Use a new project to import another baseline. Editing the mapping
in `template.json` is supported; page changes and reordered pages require matching
updates followed by a fresh prepare and review. Do not change pinned baseline files
or replace hashes to conceal a mismatch.

Read `layouts.json` before authoring. It contains:

- Actual slide order, hidden status and slide size in points.
- Referenced masters and their layouts, including unused layouts.
- Object names, types, placeholder identifiers, declared text, fonts and sizes.
- Bounds in points, with source-part provenance. Missing slide bounds inherit by
  placeholder index from the layout; layout bounds inherit by type from the master.
  Ambiguous or unresolved bounds remain null.
- Theme colors and font names. Raw XML preserves styles, backgrounds, color-map
  overrides and objects for inspection against the original package.

Only placeholder bounds are resolved. Other styling is not flattened. Interpret
text levels, theme font aliases, fills and visibility from their source XML and
reference pages. Groups, charts, SmartArt, cropped/rotated objects, effects and
external resources require manual reconstruction. Raw XML retention does not mean
the feature is supported by the native renderer or editable conversion.

Keep the user's colors, fonts, margins and repeated artwork. Preserve editability
for text and diagrams. Do not replace an entire page with a screenshot to pass a
visual check. Keep source copyright and asset notices with the project.

## 3. Prepare and inspect every mapped page

```sh
python "$SKILL_DIR/scripts/pipeline.py" prepare "$PROJECT/deck.pptd"
```

`render.json.templateComparison` lists each mapping, paired image, difference image
and normalized mean absolute pixel error. `.pipeline/template/NNNN-pair.png` labels
the template on the left and the Pillow candidate on the right. Difference images
use their absolute RGB difference after resizing to a common preview size.

Inspect each pair and the full-resolution candidate. Check margins, hierarchy,
alignment, fonts, wrapping, colors, logos, image crops, repeated furniture and
intentional content changes. Pixel error is a navigation aid; there is no automatic
pass threshold. Different content and different renderers can change many pixels
while preserving the intended layout. A low score cannot prove editable fidelity.

Record `decisions.json` with the same ordered page paths and source numbers:

```json
[
  {"page": "pages/01.page", "sourcePage": 1, "passed": true, "note": "Describe the actual checks and intentional differences."},
  {"page": "pages/02.page", "sourcePage": 2, "passed": false, "note": "Body text crosses the template's right margin; reflow before export."}
]
```

Use true only after inspecting that page. Generic copied notes are not evidence of
inspection. The CLI verifies coverage and types; it cannot verify human/model honesty.

```sh
python "$SKILL_DIR/scripts/pipeline.py" review "$PROJECT/deck.pptd" --mode visual --template-decisions "$PROJECT/decisions.json" --note "Describe the actual complete-deck inspection"
python "$SKILL_DIR/scripts/pipeline.py" export "$PROJECT/deck.pptd" --output "$PROJECT/deck.pptx"
```

Any failed page blocks pipeline export. Repair, prepare, inspect and review again.
Missing/incomplete decisions, structural review, changed references, changed page
mapping and modified comparison images cannot pass. A failed review attempt revokes
the previous approval. Review stores a copy of the decisions, bound to the current
render report and input hashes; editing the submitted decisions file alone does not
change the recorded approval. Submit another review to change it.

Template projects cannot use structural-only mode to claim template acceptance.
When visual inspection is unavailable, keep the project and report the pending step.
The reference, extract and decision reports do not certify PowerPoint/WPS/Keynote
rendering of the exported PPTX. That requires a separate application check.

The gates apply to `pipeline.py export`. The standalone exporter and editor export
remain development tools and do not produce pipeline acceptance evidence. Use the
pipeline for final delivery. Editor project copies/downloads include the pinned
template bundle and contract; approvals do not travel. Prepare and review the copy.
