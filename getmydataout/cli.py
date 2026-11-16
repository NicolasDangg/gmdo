"""gmdo: get your data out of Canvas LMS with a TinyFish agent.

  gmdo setup     sign in once, by hand, in a TinyFish browser profile
  gmdo export    export everything (first run) or only what changed (later runs)
  gmdo status    what the last export holds
  gmdo runs      recent TinyFish runs with links
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import typer

from .client import RUN_LINK, ReauthRequired, TinyFishClient
from .redact import RedactingFilter
from .state import State

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
ENV = Path(".env")


def load_env() -> None:
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def set_env(key: str, value: str) -> None:
    lines = [l for l in (ENV.read_text().splitlines() if ENV.exists() else []) if not l.startswith(key + "=")]
    ENV.write_text("\n".join(lines + [f"{key}={value}"]) + "\n")


def setup_logging(verbose: bool) -> None:
    h = logging.StreamHandler()
    h.addFilter(RedactingFilter())
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, handlers=[h])


def need(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        raise typer.BadParameter(f"{key} is not set. Run `gmdo setup` first.")
    return v


@app.command()
def setup(portal: str = typer.Option("https://lms.vinschool.edu.vn", help="Portal origin"),
          name: str = typer.Option("gmdo-canvas", help="Profile name for a new profile")):
    """Open a TinyFish browser on the portal so you can sign in by hand (SSO and MFA included)."""
    load_env()
    c = TinyFishClient()
    pid = os.environ.get("GMDO_PROFILE_ID") or c.create_profile(name)["id"]
    sess = c.start_setup_session(pid, url=portal.rstrip("/") + "/login", timeout_seconds=900)
    typer.echo("\nSign in here, in your own browser tab (nothing you type passes through this tool):")
    typer.echo(f"  {sess.get('viewer_url') or sess['base_url'] + '/stream/latest'}\n")
    typer.confirm("Signed in and looking at your dashboard?", abort=True)
    host = portal.split("//", 1)[-1].split("/")[0]
    saved = c.save_setup_session(pid, sess["session_id"], [host])
    set_env("GMDO_PROFILE_ID", pid)
    set_env("GMDO_PORTAL", portal.rstrip("/"))
    typer.echo(f"Saved {saved.get('cookie_count')} cookies to profile {pid}. No password was stored.")


@app.command("export")
def export_cmd(
    full: bool = typer.Option(False, "--full", help="Re-read every course, not only changed ones"),
    courses: str = typer.Option("", help="Comma-separated course ids to limit to"),
    terms: str = typer.Option("", help='Only these school years, e.g. "2025-2026,2026-2027"'),
    docs: str = typer.Option("own,submissions", help="Document kinds: own, submissions, course (teacher files, large), or none"),
    max_doc_mb: float = typer.Option(50, help="Skip single files larger than this"),
    budget: float = typer.Option(3.0, help="Stop if the agent cost estimate is above this (USD)"),
    out: Path = typer.Option(Path("export")), docs_dir: Path = typer.Option(Path("documents")),
    state: Path = typer.Option(Path("state.json")),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would run and the cost, spend nothing"),
    yes: bool = typer.Option(False, "--yes", help="Go ahead even if over budget"),
    no_batch: bool = typer.Option(False, "--no-batch", help="One streamed run at a time"),
    verbose: bool = typer.Option(False, "-v"),
):
    """Export grades, assignments and documents. Later runs pick up only what changed."""
    from .extract import Config, run
    load_env()
    setup_logging(verbose)
    cfg = Config(origin=need("GMDO_PORTAL"), profile_id=need("GMDO_PROFILE_ID"), out=out, docs_dir=docs_dir,
                 state_path=state, full=full, budget_usd=budget, dry_run=dry_run, yes=yes, batch=not no_batch,
                 doc_kinds=set() if docs == "none" else {d.strip() for d in docs.split(",") if d.strip()},
                 max_doc_mb=max_doc_mb or None,
                 only_courses={int(x) for x in courses.split(",") if x.strip()} or None,
                 only_terms={"".join(t.split()) for t in terms.split(",") if t.strip()} or None)
    try:
        m = run(cfg, TinyFishClient(), say=lambda s, end="\n": typer.echo(s, nl=end == "\n"))
    except ReauthRequired as e:
        typer.echo(f"Signed out: {e.message}. Run `gmdo setup` and sign in again.", err=True)
        raise typer.Exit(2)
    if m.get("dry_run"):
        typer.echo(json.dumps(m, indent=1))
        return
    ch, a = m["changes"], m["agent"]
    typer.echo(f"\n{m['records']} records · courses complete {m['courses']['complete']}/{m['courses']['total']} · "
               f"added {ch['added']} · changed {ch['changed']} · removed {ch['removed_from_portal']}")
    typer.echo(f"documents: {m['documents']}")
    typer.echo(f"agent: {a['runs']} runs, {a['steps']} steps (~${a['est_cost_usd']}) · scores verified "
               f"{m['score_checks']['verified']}, mismatched {m['score_checks']['mismatched']}")
    typer.echo(f"files in {out}/ and {docs_dir}/ · run links in {out}/manifest.json")


@app.command()
def showcase(src: Path = typer.Option(Path("export"), help="The real export to copy from"),
             dest: Path = typer.Option(Path("showcase"), help="Where the shareable copy goes"),
             hide_scores: bool = typer.Option(False, "--hide-scores", help="Also blank every score")):
    """Write a shareable copy of the export with names, handles, classes and comments removed."""
    from . import export as ex
    from .session import portal_browser
    from .showcase import Redactor, build, collect_terms
    load_env()
    courses = ex.load_table(src, "courses")
    if not courses:
        raise typer.BadParameter(f"no export in {src}/. Run `gmdo export` first.")
    with portal_browser(TinyFishClient(), need("GMDO_PROFILE_ID"), need("GMDO_PORTAL"), refresh_cookies=False) as pb:
        terms = collect_terms(pb, courses)
    s = build(src, dest, Redactor(terms), hide_scores=hide_scores)
    typer.echo(f"Showcase written to {s['dest']}/ ({s['records']} records, {s['courses']} courses, "
               f"{s['documents']} documents); {len(terms)} personal terms checked, none left.")


@app.command()
def status(state: Path = typer.Option(Path("state.json")), out: Path = typer.Option(Path("export"))):
    """Show what the last export holds."""
    st = State.load(state)
    if not st.last_export_at:
        typer.echo("No export yet. Run `gmdo export`.")
        return
    done = sum(1 for c in st.courses.values() if c.get("status") == "complete")
    typer.echo(f"last export {st.last_export_at} · {len(st.records)} records · {len(st.docs)} documents · "
               f"courses complete {done}/{len(st.courses)}")
    m = out / "manifest.json"
    if m.exists():
        man = json.loads(m.read_text())
        typer.echo(f"last run: {man['mode']} · changes {man['changes']} · agent steps {man['agent']['steps']}")


@app.command()
def runs(limit: int = typer.Option(10)):
    """List recent TinyFish runs with their links."""
    load_env()
    c = TinyFishClient()
    for i, r in enumerate(c.list_runs(limit=min(limit, 100), sort_direction="desc")):
        if i >= limit:
            break
        typer.echo(f"{r.get('created_at', '')[:19]}  {r.get('status', ''):<9}  steps {r.get('num_of_steps') or '-':>3}  "
                   f"{RUN_LINK.format(run_id=r['run_id'])}")


if __name__ == "__main__":
    app()
