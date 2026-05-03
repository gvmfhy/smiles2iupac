"""Gradio Blocks UI mounted onto the FastAPI app.

`python -m app.gradio_app` runs a single uvicorn server on :7860 that
serves the Gradio UI at `/` and the FastAPI endpoints (/health, /convert,
/batch) alongside it.
"""

from __future__ import annotations

import gradio as gr

from .api import app as api_app
from .api import pipeline

EXAMPLES: list[tuple[str, str]] = [
    ("ethanol", "CCO"),
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("caffeine", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"),
    ("L-tyrosine", "OC(=O)C(N)Cc1ccc(O)cc1"),
    ("sodium acetate (salt)", "CC(=O)[O-].[Na+]"),
]


def _format_metadata(result) -> str:
    """Render the right-hand metadata pane as Markdown.

    Always include a 'Verify on PubChem' link and a step-by-step reasoning
    trace so the user can see what the pipeline did and check the answer
    against an independent source.
    """
    if result.error:
        rows = [f"### Error\n\n`{result.error}`"]
        if result.warnings:
            rows.append("**Warnings:** " + "; ".join(result.warnings))
        if result.trace:
            rows.append(_render_trace_block(result.trace))
        return "\n\n".join(rows)

    if not result.name:
        return "### No name found\n\nThe pipeline returned no name and no error."

    rows = [
        f"### {result.name}",
        f"**Confidence:** {result.confidence:.2f}",
        f"**Source:** `{result.source.value}`",
    ]
    if result.formula:
        rows.append(f"**Formula:** {result.formula}")
    if result.mol_weight is not None:
        rows.append(f"**MW:** {result.mol_weight:.3f} g/mol")
    if result.inchikey:
        rows.append(f"**InChIKey:** `{result.inchikey}`")
    if result.alternatives:
        rows.append("**Synonyms:** " + ", ".join(result.alternatives[:5]))
    if result.warnings:
        rows.append("**Warnings:** " + "; ".join(result.warnings))
    if result.pubchem_url:
        rows.append(
            f"[🔗 Verify on PubChem]({result.pubchem_url}) "
            "— compare structure + canonical name independently"
        )
    if result.trace:
        rows.append(_render_trace_block(result.trace))
    return "\n\n".join(rows)


def _render_trace_block(trace: list[str]) -> str:
    """Render the reasoning trace as a Markdown <details> block.

    Collapsed by default so the result name stays prominent; expandable for
    users who want to see exactly what the pipeline did.
    """
    body = "\n".join(f"{i}. {step}" for i, step in enumerate(trace, 1))
    return f"<details><summary><b>How we got this answer</b></summary>\n\n{body}\n\n</details>"


def _wrap_svg_responsive(svg: str) -> str:
    """Wrap an RDKit-emitted SVG so it scales with its container.

    RDKit emits fixed width/height attributes (e.g. width="300px" height="300px"),
    which on narrow viewports overflow the column and overlap the adjacent
    metadata pane. Wrapping in a max-width-100% container with a centered cap
    keeps it readable on mobile and bounded on desktop.
    """
    return (
        '<div style="max-width:300px;margin:0 auto;">'
        '<style>div > svg { width:100% !important; height:auto !important; }</style>'
        f'{svg}'
        '</div>'
    )


def _convert(smiles: str) -> tuple[str, str]:
    if not smiles or not smiles.strip():
        return ("", "_Enter a SMILES string above and click Convert._")

    # Per-call kwarg — never mutate the shared pipeline (Gradio runs handlers
    # in a threadpool, same race issue as FastAPI).
    result = pipeline.convert(smiles.strip(), include_svg=True)

    if result.structure_svg:
        svg_html = _wrap_svg_responsive(result.structure_svg)
    else:
        svg_html = "<p><em>No structure preview available.</em></p>"
    return (svg_html, _format_metadata(result))


with gr.Blocks(title="smiles2iupac") as demo:
    gr.Markdown(
        "# smiles2iupac\n"
        "Reliable SMILES -> IUPAC name conversion. "
        "Cache + PubChem lookup with provenance and confidence scoring.  \n"
        "[Source on GitHub](https://github.com/gvmfhy/smiles2iupac) · "
        "[API docs](https://agwgwa-smiles2iupac.hf.space/docs)"
    )
    with gr.Row():
        smiles_in = gr.Textbox(
            label="SMILES",
            placeholder="e.g. CCO",
            scale=4,
            autofocus=True,
        )
        submit = gr.Button("Convert", variant="primary", scale=1)

    # gr.Column accepts min_width — phones (~375px wide) end up under the combined
    # min_width and Gradio stacks the columns vertically. Tablet+ keeps them in a row.
    with gr.Row(equal_height=False):
        with gr.Column(min_width=320):
            svg_out = gr.HTML(label="Structure")
        with gr.Column(min_width=320):
            meta_out = gr.Markdown(label="Result", value="_Results will appear here._")

    # Manual chip buttons (vs gr.Examples which rendered phantom skeleton rows
    # in gradio 6.14). Each button fills the textbox and triggers convert.
    gr.Markdown("**Examples** — click to try")
    with gr.Row():
        example_buttons = [
            gr.Button(label, size="sm", scale=0) for label, _smi in EXAMPLES
        ]

    submit.click(_convert, inputs=[smiles_in], outputs=[svg_out, meta_out])
    smiles_in.submit(_convert, inputs=[smiles_in], outputs=[svg_out, meta_out])

    # Wire each example button: fill textbox with the SMILES, then run convert.
    for btn, (_label, smi) in zip(example_buttons, EXAMPLES):
        btn.click(
            lambda s=smi: s, inputs=None, outputs=[smiles_in]
        ).then(_convert, inputs=[smiles_in], outputs=[svg_out, meta_out])


# Mount Gradio on top of FastAPI so /, /convert, /health, /batch all live
# on the same server. ssr_mode=False avoids requiring a local Node install.
app = gr.mount_gradio_app(api_app, demo, path="/", ssr_mode=False)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
