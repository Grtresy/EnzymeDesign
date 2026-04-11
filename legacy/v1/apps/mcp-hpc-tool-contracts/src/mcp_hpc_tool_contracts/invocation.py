from __future__ import annotations

import os


def build_sif_command(
    *,
    image: str,
    entrypoint: str,
    args: list[str],
    use_run: bool = False,
    extra_runtime_args: list[str] | None = None,
    extra_host_binds: list[str] | None = None,
) -> list[str]:
    """Build an apptainer exec/run command.

    Args:
        extra_host_binds: Host paths to bind into the container at the same
            path (e.g. ``["/db", "/models"]``).  Each entry may be a bare
            path (``"/db"`` → ``/db:/db``) or an explicit ``src:dst`` pair.
            The standard work/out/tmp bind mounts are always included.
    """
    subcommand = "run" if use_run else "exec"
    command = [
        "apptainer",
        subcommand,
        "--cleanenv",
        "--bind",
        ".:/work",
        "--bind",
        "../out:/out",
        "--bind",
        "../tmp:/tmp",
    ]
    for bind_path in extra_host_binds or []:
        bind_spec = bind_path if ":" in bind_path else f"{bind_path}:{bind_path}"
        command.extend(["--bind", bind_spec])
    if extra_runtime_args:
        command.extend(extra_runtime_args)
    # Expand leading ~/ so shlex.join in the sbatch generator does not
    # single-quote the tilde, which would prevent shell expansion on the remote.
    command.append(os.path.expanduser(image))
    if not use_run:
        command.append(entrypoint)
    command.extend(args)
    return command
