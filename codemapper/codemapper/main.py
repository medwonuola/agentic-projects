import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from codemapper.daemon import Daemon, DaemonClient, PID_FILE

app = typer.Typer(
    name="mapper",
    help="CodeMapper - Local codebase mapping daemon with scheduled LLM-powered code summarization",
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

HELP_TEXT = """
[bold cyan]CodeMapper[/bold cyan] - LLM-powered codebase documentation daemon

[bold]DAEMON COMMANDS[/bold]
  [cyan]serve[/cyan]     Start the daemon (add -b for background)
  [cyan]stop[/cyan]      Stop the running daemon
  [cyan]status[/cyan]    Check if daemon is running

[bold]CODEBASE MANAGEMENT[/bold]
  [cyan]scan[/cyan]      Register or run a scan
              mapper scan /path --every 30m   # Schedule
              mapper scan /path --once        # One-time
  [cyan]list[/cyan]      List registered codebases
  [cyan]remove[/cyan]    Unregister a codebase
  [cyan]run[/cyan]       Trigger scan for registered codebase

[bold]MONITORING[/bold]
  [cyan]ps[/cyan]        Show running scans
  [cyan]jobs[/cyan]      Show scan history
  [cyan]logs[/cyan]      View logs (by job ID or codebase name)

[bold]ANALYSIS[/bold]
  [cyan]deps[/cyan]      Show dependency graph and import stats
  [cyan]cycles[/cyan]    Detect circular dependencies

[bold]EXAMPLES[/bold]
  mapper deps ~/code                 # Analyze imports
  mapper cycles ~/code               # Find circular deps
  mapper deps ~/code --mermaid       # Output mermaid diagram
"""


def relative_time(iso_str: str | None) -> str:
    if not iso_str:
        return "never"
    dt = datetime.fromisoformat(iso_str)
    delta = datetime.now() - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h ago"
    if delta.seconds >= 60:
        return f"{delta.seconds // 60}m ago"
    return f"{delta.seconds}s ago"


@app.command(help="Start the CodeMapper daemon")
def serve(
    background: Annotated[bool, typer.Option("--background", "-b", help="Run in background")] = False,
) -> None:
    if DaemonClient.is_running():
        console.print("[yellow]Daemon already running[/yellow]")
        raise typer.Exit(1)

    if background:
        pid = os.fork()
        if pid > 0:
            console.print(f"[green]✓[/green] Daemon started in background (PID: {pid})")
            return
        os.setsid()
        sys.stdin.close()
        sys.stdout = open("/dev/null", "w")
        sys.stderr = open("/dev/null", "w")

    console.print("[bold blue]CodeMapper[/bold blue] daemon starting...")
    console.print("Socket: /tmp/codemapper.sock")
    console.print("Press Ctrl+C to stop\n")

    daemon = Daemon()

    async def run_daemon() -> None:
        await daemon.start()
        try:
            while daemon._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await daemon.stop()

    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        asyncio.run(daemon.stop())
    console.print("[green]Daemon stopped[/green]")


@app.command(help="Register a codebase for scheduled scanning (or one-time with --once)")
def scan(
    path: Annotated[Path, typer.Argument(help="Path to codebase")],
    every: Annotated[str | None, typer.Option("--every", "-e", help="Interval: 30s, 5m, 2h, 1d")] = None,
    cron: Annotated[str | None, typer.Option("--cron", "-c", help="Cron: '0 */2 * * *'")] = None,
    once: Annotated[bool, typer.Option("--once", "-o", help="Run once now (no schedule)")] = False,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Custom name for codebase")] = None,
) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        console.print(f"[red]Error:[/red] Path {resolved} does not exist")
        raise typer.Exit(1)

    if once:
        response = asyncio.run(DaemonClient.send("run_once", path=str(resolved)))
        if response["ok"]:
            console.print(f"[green]✓[/green] {response['message']}")
        else:
            console.print(f"[red]✗[/red] {response['message']}")
            raise typer.Exit(1)
        return

    codebase_name = name or resolved.name
    schedule = f"every {every}" if every else cron

    if not schedule:
        console.print("[red]Error:[/red] Specify --every, --cron, or --once")
        console.print("[dim]Examples: --every 30m, --cron '0 */2 * * *', --once[/dim]")
        raise typer.Exit(1)

    response = asyncio.run(DaemonClient.send("scan", name=codebase_name, path=str(resolved), schedule=schedule))

    if response["ok"]:
        console.print(f"[green]✓[/green] {response['message']}")
    else:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)


@app.command(help="Trigger an immediate scan for a registered codebase")
def run(
    name: Annotated[str, typer.Argument(help="Codebase name")],
) -> None:
    response = asyncio.run(DaemonClient.send("run", name=name))

    if response["ok"]:
        console.print(f"[green]✓[/green] {response['message']}")
    else:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)


@app.command(name="list", help="List all registered codebases")
def list_codebases() -> None:
    response = asyncio.run(DaemonClient.send("list"))

    if not response["ok"]:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)

    codebases = response.get("codebases", [])
    if not codebases:
        console.print("[dim]No codebases registered[/dim]")
        console.print("[dim]Use: mapper scan /path --every 30m[/dim]")
        return

    table = Table(title="Registered Codebases")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Schedule", style="green")
    table.add_column("Last Run", style="yellow")

    for cb in codebases:
        table.add_row(cb["name"], cb["path"], cb["schedule"], relative_time(cb.get("last_run")))

    console.print(table)


@app.command(help="Show currently running scans")
def ps() -> None:
    response = asyncio.run(DaemonClient.send("ps"))

    if not response["ok"]:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)

    jobs = response.get("jobs", [])
    if not jobs:
        console.print("[dim]No running jobs[/dim]")
        return

    table = Table(title="Running Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Codebase", style="white")
    table.add_column("Status", style="green")
    table.add_column("Started", style="yellow")

    for job in jobs:
        table.add_row(job["id"], job["codebase"], job["status"], relative_time(job.get("started")))

    console.print(table)


@app.command(help="Show scan history")
def jobs(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of jobs")] = 20,
) -> None:
    response = asyncio.run(DaemonClient.send("jobs", limit=limit))

    if not response["ok"]:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)

    jobs_list = response.get("jobs", [])
    if not jobs_list:
        console.print("[dim]No jobs found[/dim]")
        return

    table = Table(title="Job History")
    table.add_column("ID", style="cyan")
    table.add_column("Codebase", style="white")
    table.add_column("Status", style="green")
    table.add_column("Files", style="dim")
    table.add_column("Symbols", style="dim")
    table.add_column("Started", style="yellow")

    for job in jobs_list:
        status_style = "green" if job["status"] == "completed" else "red" if job["status"] == "failed" else "yellow"
        table.add_row(
            job["id"],
            job["codebase"],
            f"[{status_style}]{job['status']}[/{status_style}]",
            str(job.get("files", 0)),
            str(job.get("symbols", 0)),
            relative_time(job.get("started"))
        )

    console.print(table)


@app.command(help="View logs for a specific job")
def logs(
    job_id: Annotated[str, typer.Argument(help="Job ID (from 'mapper jobs')")],
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of lines")] = 100,
) -> None:
    response = asyncio.run(DaemonClient.send("logs", job_id=job_id, limit=limit))

    if not response["ok"]:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)

    logs_list = response.get("logs", [])
    if not logs_list:
        console.print("[dim]No logs found[/dim]")
        return

    for log in logs_list:
        ts = log["timestamp"].split("T")[1].split(".")[0]
        level = log["level"]
        level_style = "red" if level == "error" else "yellow" if level == "warn" else "dim"
        console.print(f"[dim]{ts}[/dim] [{level_style}]{level.upper():5}[/{level_style}] {log['message']}")


@app.command(help="Unregister a codebase")
def remove(
    name: Annotated[str, typer.Argument(help="Codebase name")],
) -> None:
    response = asyncio.run(DaemonClient.send("remove", name=name))

    if response["ok"]:
        console.print(f"[green]✓[/green] {response['message']}")
    else:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)


@app.command(help="Stop the running daemon")
def stop() -> None:
    if not DaemonClient.is_running():
        console.print("[dim]Daemon not running[/dim]")
        return

    response = asyncio.run(DaemonClient.send("stop"))

    if response["ok"]:
        console.print(f"[green]✓[/green] {response['message']}")
    else:
        console.print(f"[red]✗[/red] {response['message']}")
        raise typer.Exit(1)


@app.command(help="Check if daemon is running")
def status() -> None:
    if DaemonClient.is_running():
        response = asyncio.run(DaemonClient.send("ping"))
        if response["ok"]:
            pid = PID_FILE.read_text() if PID_FILE.exists() else "?"
            console.print(f"[green]●[/green] Daemon running (PID: {pid})")
            return
    console.print("[red]●[/red] Daemon not running")


@app.command(help="Analyze dependencies and show import stats")
def deps(
    path: Annotated[Path, typer.Argument(help="Path to codebase")] = Path("."),
    mermaid: Annotated[bool, typer.Option("--mermaid", "-m", help="Output mermaid diagram")] = False,
) -> None:
    from codemapper.processor.graph import ProjectAnalyzer

    resolved = path.resolve()
    if not resolved.exists():
        console.print(f"[red]Error:[/red] Path {resolved} does not exist")
        raise typer.Exit(1)

    console.print(f"[dim]Analyzing {resolved}...[/dim]")
    analyzer = ProjectAnalyzer(resolved)
    graph = analyzer.analyze()
    stats = graph.get_stats()

    if mermaid:
        console.print(graph.to_mermaid())
        return

    console.print(f"\n[bold]Dependency Analysis[/bold]\n")
    console.print(f"  Modules:          {stats.total_modules}")
    console.print(f"  Total imports:    {stats.total_imports}")
    console.print(f"  Internal:         {stats.internal_imports}")
    console.print(f"  External:         {stats.external_imports}")
    console.print(f"  Circular deps:    [{'red' if stats.cycles else 'green'}]{len(stats.cycles)}[/]")

    if stats.most_imported:
        console.print(f"\n[bold]Most Imported[/bold]")
        for module, count in stats.most_imported[:5]:
            console.print(f"  {count:3}x  {module}")

    if stats.most_dependencies:
        console.print(f"\n[bold]Most Dependencies[/bold]")
        for module, count in stats.most_dependencies[:5]:
            console.print(f"  {count:3}   {module}")


@app.command(help="Detect circular dependencies")
def cycles(
    path: Annotated[Path, typer.Argument(help="Path to codebase")] = Path("."),
) -> None:
    from codemapper.processor.graph import ProjectAnalyzer

    resolved = path.resolve()
    if not resolved.exists():
        console.print(f"[red]Error:[/red] Path {resolved} does not exist")
        raise typer.Exit(1)

    console.print(f"[dim]Analyzing {resolved}...[/dim]")
    analyzer = ProjectAnalyzer(resolved)
    graph = analyzer.analyze()
    found_cycles = graph.find_cycles()

    if not found_cycles:
        console.print("[green]✓[/green] No circular dependencies found")
        return

    console.print(f"[red]✗[/red] Found {len(found_cycles)} circular dependencies:\n")
    for i, cycle in enumerate(found_cycles, 1):
        console.print(f"  {i}. [yellow]{cycle}[/yellow]")


@app.command(name="help", help="Show detailed help")
def show_help() -> None:
    console.print(Panel(HELP_TEXT, title="CodeMapper Help", border_style="blue"))


if __name__ == "__main__":
    app()

