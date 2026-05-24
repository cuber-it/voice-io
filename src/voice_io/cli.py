"""CLI entry point for voice-io."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console

from voice_io.config import load_config

app = typer.Typer(
    help="voice-io \u2014 local voice recording and transcription service.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def listen(
    config_path: Path | None = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the daemon (terminal mode). Listens for wake-word."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    config = load_config(config_path)

    console.print(f"[bold]voice-io[/] listening for [cyan]{config.wakeword.word}[/]")
    console.print(f"  stop phrase: [cyan]{config.wakeword.stop_phrase}[/]")
    console.print(f"  model: [yellow]{config.transcription.model}[/]")
    console.print(f"  output: {config.general.vault_dir}")
    console.print(f"  silence timeout: {config.recording.silence_timeout}s")
    console.print("[dim]  Ctrl+C to quit.[/]\n")

    from voice_io.daemon import Daemon
    daemon = Daemon(config)
    daemon.run()


@app.command()
def serve(
    config_path: Path | None = typer.Option(None, "--config", "-c"),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(12120, "--port"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the web GUI + daemon."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    config = load_config(config_path)

    console.print(f"[bold]voice-io[/] web GUI starting")
    console.print(f"  http://{host}:{port}")
    console.print(f"  wake-word: [cyan]{config.wakeword.word}[/]")
    console.print(f"  stop phrase: [cyan]{config.wakeword.stop_phrase}[/]")
    console.print(f"  model: [yellow]{config.transcription.model}[/]\n")

    import uvicorn
    from voice_io.api import create_app

    fastapi_app = create_app(config)
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app.command()
def devices() -> None:
    """List available audio input devices."""
    import sounddevice as sd
    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("Name")
    table.add_column("Ch In", justify="right")
    table.add_column("Default SR", justify="right")

    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            table.add_row(
                str(idx),
                dev["name"],
                str(dev["max_input_channels"]),
                f"{int(dev['default_samplerate'])} Hz",
            )

    console.print(table)


if __name__ == "__main__":
    app()
