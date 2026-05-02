"""Command-line interface for smiles2iupac.

Single-command design — `s2i SMILES` is the common case. Batch and info modes
are flag-driven to avoid Click's awkward interaction between default positionals
and subcommands.
"""

import csv
import json
import sys
from pathlib import Path

import click

from .pipeline import Pipeline


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("smiles", required=False)
@click.option(
    "-r", "--reverse",
    "reverse_name",
    metavar="NAME",
    help="Reverse lookup: resolve a chemical name (IUPAC or common) to SMILES.",
)
@click.option("-j", "--json", "as_json", is_flag=True, help="Emit JSON instead of text.")
@click.option(
    "--batch",
    "batch_input",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="CSV file of SMILES to convert in batch.",
)
@click.option(
    "-o",
    "--output",
    "batch_output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output CSV path for batch mode (defaults to <input>.named.csv).",
)
@click.option("--column", default="smiles", help="Column name in the input CSV (default: smiles).")
@click.option("--info", is_flag=True, help="Show pipeline info and cache stats.")
@click.option("--no-pubchem", is_flag=True, help="Skip PubChem lookup (cache only).")
@click.option(
    "--use-stout",
    is_flag=True,
    help="Enable STOUT v2 generation for molecules not found in PubChem (requires [ml] extras).",
)
@click.option(
    "--synonyms", is_flag=True, help="Include common-name synonyms as alternatives."
)
@click.option(
    "--include-svg",
    is_flag=True,
    help="Include structure SVG in JSON output (large; off by default).",
)
@click.option(
    "--include-cas",
    is_flag=True,
    help="Look up CAS Registry Number from PubChem (extra request per molecule).",
)
@click.version_option(package_name="smiles2iupac")
def main(
    smiles: str | None,
    reverse_name: str | None,
    as_json: bool,
    batch_input: Path | None,
    batch_output: Path | None,
    column: str,
    info: bool,
    no_pubchem: bool,
    use_stout: bool,
    synonyms: bool,
    include_svg: bool,
    include_cas: bool,
):
    """Convert a SMILES string to its IUPAC name (or vice-versa).

    \b
    Examples:
      s2i CCO                          → ethanol
      s2i 'CC(=O)Oc1ccccc1C(=O)O'      → 2-acetyloxybenzoic acid (aspirin)
      s2i CCO --json                   → full JSON (InChIKey, formula, MW, ...)
      s2i 'CC(=O)[O-].[Na+]'           → acetate (salt parent named, counter-ion stripped)
      s2i --reverse 'aspirin'          → CC(=O)Oc1ccccc1C(=O)O  (reverse: name → SMILES)
      s2i --batch input.csv -o out.csv → batch convert
      s2i --info                       → cache stats
    """
    if info:
        _emit_info()
        return

    if reverse_name is not None:
        from .pipeline import lookup
        smi = lookup(reverse_name, use_pubchem=not no_pubchem)
        if smi is None:
            click.echo(f"<no SMILES found for {reverse_name!r}>", err=True)
            sys.exit(1)
        click.echo(smi)
        sys.exit(0)

    pipeline = Pipeline(
        use_pubchem=not no_pubchem,
        use_stout=use_stout,
        fetch_synonyms=synonyms,
        include_svg=include_svg,
        include_cas=include_cas,
    )

    if batch_input is not None:
        out_path = batch_output or batch_input.with_suffix(".named.csv")
        _run_batch(pipeline, batch_input, out_path, column)
        return

    if not smiles:
        ctx = click.get_current_context()
        click.echo(ctx.get_help())
        sys.exit(0)

    result = pipeline.convert(smiles)
    if as_json:
        click.echo(result.model_dump_json(indent=2))
    else:
        click.echo(_format_text(result))
    sys.exit(0 if result.ok else 1)


def _format_text(result) -> str:
    """Multi-line human-readable output. The base __str__ shows just name+conf+warnings;
    here we add enrichment fields when present."""
    if result.error:
        return f"<error: {result.error}>"
    if not result.name:
        return "<no name found>"
    lines = [
        f"{result.name}  (confidence: {result.confidence:.2f}, source: {result.source.value})",
    ]
    if result.formula:
        lines.append(f"  formula: {result.formula}    MW: {result.mol_weight:.3f}")
    if result.inchikey:
        lines.append(f"  InChIKey: {result.inchikey}")
    if result.cas:
        lines.append(f"  CAS: {result.cas}")
    if result.alternatives:
        lines.append(f"  also known as: {', '.join(result.alternatives[:3])}")
    if result.warnings:
        lines.append("  warnings: " + "; ".join(result.warnings))
    return "\n".join(lines)


def _emit_info() -> None:
    pipeline = Pipeline()
    payload = {
        "version": _version(),
        "cache_path": str(pipeline.cache.db_path),
        "cache_size": pipeline.cache.size(),
    }
    click.echo(json.dumps(payload, indent=2))


def _version() -> str:
    from . import __version__
    return __version__


def _run_batch(pipeline: Pipeline, input_path: Path, output_path: Path, column: str) -> None:
    with open(input_path) as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            click.echo(f"error: column {column!r} not in {input_path}", err=True)
            sys.exit(2)
        rows = list(reader)

    if not rows:
        click.echo(f"error: no rows in {input_path}", err=True)
        sys.exit(2)

    extra_fields = ["iupac_name", "confidence", "source", "inchikey", "formula", "mol_weight", "kind", "warnings", "error"]
    output_fields = list(rows[0].keys()) + extra_fields
    with open(output_path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        with click.progressbar(rows, label="Converting") as bar:
            for row in bar:
                result = pipeline.convert(row[column])
                row.update({
                    "iupac_name": result.name or "",
                    "confidence": f"{result.confidence:.2f}",
                    "source": result.source.value,
                    "inchikey": result.inchikey or "",
                    "formula": result.formula or "",
                    "mol_weight": f"{result.mol_weight:.4f}" if result.mol_weight else "",
                    "kind": result.kind,
                    "warnings": "; ".join(result.warnings),
                    "error": result.error or "",
                })
                writer.writerow(row)
    click.echo(f"wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
