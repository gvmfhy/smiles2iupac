"""Gradio Blocks UI mounted onto the FastAPI app.

`python -m app.gradio_app` runs a single uvicorn server on :7860 that
serves the Gradio UI at `/` and the FastAPI endpoints (/health, /convert,
/batch) alongside it.
"""

from __future__ import annotations

import gradio as gr

from .api import app as api_app
from .api import pipeline

EXAMPLES = [
    ["CCO"],
    ["CC(=O)Oc1ccccc1C(=O)O"],
    ["CN1C=NC2=C1C(=O)N(C(=O)N2C)C"],
    ["C1=CC=C(C=C1)C2=CN(C=N2)C"],
    ["OC(=O)C(N)Cc1ccc(O)cc1"],
]


def _format_metadata(result) -> str:
    """Render the right-hand metadata pane as Markdown."""
    if result.error:
        lines = [f"### Error\n\n`{result.error}`"]
        if result.warnings:
            lines.append("**Warnings:** " + "; ".join(result.warnings))
        return "\n\n".join(lines)

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
    return "\n\n".join(rows)


def _convert(smiles: str) -> tuple[str, str]:
    if not smiles or not smiles.strip():
        return ("", "_Enter a SMILES string above and click Convert._")

    # Per-call kwarg — never mutate the shared pipeline (Gradio runs handlers
    # in a threadpool, same race issue as FastAPI).
    result = pipeline.convert(smiles.strip(), include_svg=True)

    svg_html = result.structure_svg or "<p><em>No structure preview available.</em></p>"
    return (svg_html, _format_metadata(result))


with gr.Blocks(title="smiles2iupac") as demo:
    gr.Markdown(
        "# smiles2iupac\n"
        "Reliable SMILES -> IUPAC name conversion. "
        "Cache + PubChem lookup with provenance and confidence scoring."
    )
    with gr.Row():
        smiles_in = gr.Textbox(
            label="SMILES",
            placeholder="e.g. CCO",
            scale=4,
            autofocus=True,
        )
        submit = gr.Button("Convert", variant="primary", scale=1)

    with gr.Row():
        svg_out = gr.HTML(label="Structure")
        meta_out = gr.Markdown(label="Result", value="_Results will appear here._")

    gr.Examples(examples=EXAMPLES, inputs=[smiles_in])

    submit.click(_convert, inputs=[smiles_in], outputs=[svg_out, meta_out])
    smiles_in.submit(_convert, inputs=[smiles_in], outputs=[svg_out, meta_out])


# Mount Gradio on top of FastAPI so /, /convert, /health, /batch all live
# on the same server. ssr_mode=False avoids requiring a local Node install.
app = gr.mount_gradio_app(api_app, demo, path="/", ssr_mode=False)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
