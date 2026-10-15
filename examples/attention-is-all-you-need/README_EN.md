# Attention Is All You Need · Paper presentation

[中文](README.md)

Give an agent a paper and one prompt, and let it prepare a lab meeting presentation.
This example includes the original input, final PPTX and editable PPTD project.

## Original input

Attachment: `1706.03762v7.pdf`, 15 pages.
Source: [Attention Is All You Need, arXiv v7](https://arxiv.org/abs/1706.03762v7).

The exact original prompt is also saved in [prompt.txt](prompt.txt):

> 请把这篇论文做成一份适合组会汇报的中文 PPT，讲清核心方法、关键实验和局限，图示尽量直观。

Translation: Turn this paper into a Chinese presentation for a lab meeting. Explain the core method, key experiments and limitations, with clear diagrams.

The subagent started in a fresh context and used this repository's [presentation skill](../../skills/pptd-deck-skill/SKILL.md).
No outline, slide count or design instructions were supplied.
The execution environment specified the output folder and dependencies.
The skill workflow prepares the project, visually checks every slide and repairs layout issues before export.

## Output

The agent chose 20 slides: 19 presentation slides and one reproduction appendix.

- [Download the PPTX](deck.pptx)
- [Download the editable project ZIP](project.zip)
- [View the PPTD manifest](deck.pptd)
- [View slide previews](previews/INDEX.md)

Text, equations, diagrams and charts retain editable structures.
Comparison graphics and tables in this example consist of editable shapes, lines and text.
Slide sources are in `pages/`. [evidence.json](evidence.json) records citations and experimental context.
[brief.json](brief.json) records the audience and presentation goals.
The paper PDF and font files are not bundled.

## Try and edit

After installing dependencies at the repository root, run:

```sh
uv run --locked node bin/pptd-deck-skill.js serve examples/attention-is-all-you-need --open
```

The web editor opens this project. Select a slide and an element, edit its text, equations or shapes, then save and export.
You can also extract the project ZIP and replace the folder in this command with the extracted folder.

To generate a new presentation, download the same paper version, attach it in a fresh agent conversation with this skill installed, and paste the original prompt.
The agent chooses the slide count, content structure and design.

This example references system fonts without embedding them.
On another machine, select an installed Chinese font in the editor.
To rerun strict layout checks, configure local font mappings and follow the [pipeline guide](../../skills/pptd-deck-skill/reference/pipeline.md) to prepare, review and export.

Pillow provides the layout previews. The editor screenshot shows the actual web interface.
Rendering has not been verified in PowerPoint, WPS or Keynote.

## Source

Vaswani et al. *Attention Is All You Need*. NeurIPS 2017, arXiv:1706.03762v7.
Input PDF SHA-256:

```text
bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697
```

The public example does not include the paper PDF. The agent redrew method diagrams as native objects, with citations for paper facts and data.
This example follows the repository's [MIT license](../../LICENSE). Rights to the paper remain with its authors and rights holders.
