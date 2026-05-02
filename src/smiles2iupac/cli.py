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
    "--synonyms", is_flag=True, help="Include common-name synonyms as alternatives."
)
@click.version_option(package_name="smiles2iupac")
def main(
    smiles: str | None,
    as_json: bool,
    batch_input: Path | None,
    batch_output: Path | None,
    column: str,
    info: bool,
    no_pubchem: bool,
    synonyms: bool,
):
    """Convert a SMILES string to its IUPAC name.

    \b
    Examples:
      s2i CCO                          → ethanol
      s2i 'CC(=O)Oc1ccccc1C(=O)O'      → 2-acetyloxybenzoic acid (aspirin)
      s2i CCO --json                   → JSON output
      s2i --batch input.csv -o out.csv → batch convert
      s2i --info                       → cache stats
    """
    if info:
        _emit_info()
        return

    pipeline = Pipeline(use_pubchem=not no_pubchem, fetch_synonyms=synonyms)

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
        click.echo(str(result))
    sys.exit(0 if result.ok else 1)


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

    output_fields = list(rows[0].keys()) + ["iupac_name", "confidence", "source", "error"]
    with open(output_path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        with click.progressbar(rows, label="Converting") as bar:
            for row in bar:
                result = pipeline.convert(row[column])
                row.update(
                    {
                        "iupac_name": result.name or "",
                        "confidence": f"{result.confidence:.2f}",
                        "source": result.source.value,
                        "error": result.error or "",
                    }
                )
                writer.writerow(row)
    click.echo(f"wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
