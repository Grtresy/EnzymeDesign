from __future__ import annotations

from pathlib import Path

from ..models import ConversionResult

_EXTENSION_ALIASES = {
    "cif": "cif",
    "ent": "pdb",
    "mol2": "mol2",
    "pdb": "pdb",
    "pdbqt": "pdbqt",
    "sd": "sdf",
    "sdf": "sdf",
}
_SUPPORTED_FORMATS = set(_EXTENSION_ALIASES.values())


def _normalize_format(fmt: str) -> str:
    normalized = fmt.strip().lower().lstrip(".")
    mapped = _EXTENSION_ALIASES.get(normalized)
    if mapped is None:
        supported = ", ".join(sorted(_SUPPORTED_FORMATS))
        raise ValueError(f"Unsupported format '{fmt}'. Supported formats: {supported}")
    return mapped


def _detect_input_format(input_path: Path) -> str:
    if not input_path.suffix:
        raise ValueError(f"Cannot infer input format from path: {input_path}")
    return _normalize_format(input_path.suffix)


def _resolve_output_path(input_path: Path, fmt_out: str, output_path: str | Path | None) -> Path:
    if output_path is None:
        return input_path.with_suffix(f".{fmt_out}")
    return Path(output_path)


def _load_openbabel_module() -> object:
    try:
        import openbabel as ob_pkg
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError(
            "openbabel import failed. Install preprocess-backend dependencies with uv sync."
        ) from exc

    return getattr(ob_pkg, "openbabel", ob_pkg)


def _convert_with_openbabel(
    input_path: Path,
    fmt_in: str,
    fmt_out: str,
    output_path: Path,
) -> None:
    ob = _load_openbabel_module()
    conversion = ob.OBConversion()
    if not conversion.SetInAndOutFormats(fmt_in, fmt_out):
        raise ValueError(f"OpenBabel does not support conversion {fmt_in} -> {fmt_out}")

    molecule = ob.OBMol()
    if not conversion.ReadFile(molecule, str(input_path)):
        raise ValueError(f"Failed to read molecular file: {input_path}")

    if not conversion.WriteFile(molecule, str(output_path)):
        raise RuntimeError(f"Failed to write converted molecular file: {output_path}")
    conversion.CloseOutFile()


def convert_format(
    input_path: str | Path,
    fmt_out: str,
    output_path: str | Path | None = None,
) -> ConversionResult:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Input file does not exist: {src}")

    detected_fmt = _detect_input_format(src)
    target_fmt = _normalize_format(fmt_out)
    dest = _resolve_output_path(src, target_fmt, output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    _convert_with_openbabel(src, detected_fmt, target_fmt, dest)

    return ConversionResult(
        input_path=str(src),
        output_path=str(dest),
        fmt_in=detected_fmt,
        fmt_out=target_fmt,
    )
