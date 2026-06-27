"""ActGuard command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from actguard import __version__
from actguard.config import REPO_ROOT, chroma_dir, dir_size_mb, llm_status_line, session_path
from actguard.pipeline import list_questions, run_local_scan, submit_answers
from actguard.session import load_session, require_session, save_session


def _progress(msg: str) -> None:
    print(f"  {msg}")


def cmd_setup(_: argparse.Namespace) -> int:
    print("ActGuard setup\n")
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        print(f"  ! Copy env.example to {env_file} and set MISTRAL_API_KEY (or Ollama URL).")
    else:
        print(f"  ✓ Found {env_file}")

    chroma = chroma_dir()
    if chroma.is_dir() and any(chroma.iterdir()):
        print(f"  ✓ RAG index present at {chroma}")
    else:
        print("  Building legal RAG index (one-time, may take a few minutes)…")
        from legal_rag.build_index import build_index

        build_index()
        print("  ✓ RAG index built")

    print(f"  {llm_status_line()}")
    print("  Mode: local BYOK — bring your own LLM API key")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    repo = Path(args.path).resolve()
    if not repo.is_dir():
        print(f"Error: not a directory: {repo}", file=sys.stderr)
        return 1
    print(f"Scanning {repo}…")
    try:
        session = run_local_scan(
            repo,
            progress_callback=_progress,
            skip_readiness_review=args.fast,
        )
    except Exception as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        return 1
    out = save_session(repo, session)
    flags = session["scan_summary"].get("profile_flags", [])
    print(f"\n✓ Scan complete — session saved to {out}")
    if flags:
        print("  Flags: " + ", ".join(flags))
    score = (session.get("readiness") or {}).get("final_overall")
    if score is not None:
        readiness = session["readiness"]
        active = readiness.get("active_regulations") or []
        triggered = readiness.get("triggered_rules") or []
        print(f"  Readiness score: {score}/100", end="")
        if active:
            print(f" (avg of {', '.join(active)})", end="")
        print()
        if triggered:
            print(
                f"  Triggered {len(triggered)} readiness rule(s): "
                + ", ".join(r["id"] for r in triggered[:5])
            )
            if len(triggered) > 5:
                print(f"    … and {len(triggered) - 5} more")
    synthesis = (session.get("state") or {}).get("deep_synthesis") or {}
    meta = synthesis.get("_meta") or {}
    files_analyzed = meta.get("files_analyzed")
    if files_analyzed:
        print(f"  Deep analysis: {files_analyzed} file(s) reviewed")
    if synthesis.get("_used_fallback") or meta.get("used_fallback"):
        err = synthesis.get("_synthesis_error") or "LLM synthesis unavailable"
        print(f"  ! Partial analysis only — {err}")
        print("    Set MISTRAL_API_KEY in .env for full per-file AI review.")
    sp = (session.get("state") or {}).get("scores_people", {})
    if sp.get("value"):
        print("  ! Automated scoring/decisions about people detected")
        for ev in (sp.get("evidence") or [])[:2]:
            print(f"    · {ev}")
    print("\nNext: actguard questions  →  actguard answer  →  actguard generate report")
    return 0


def cmd_questions(args: argparse.Namespace) -> int:
    repo = Path(args.path or ".").resolve()
    session = require_session(repo)
    questions = list_questions(session)
    if not questions:
        print("No questions needed — run: actguard answer --submit")
        return 0
    print(f"Questions for {repo}:\n")
    for i, q in enumerate(questions, 1):
        print(f"{i}. [{q['key']}] {q['q']}")
        if q.get("help"):
            print(f"   ({q['help']})")
        for j, opt in enumerate(q.get("opts") or [], 1):
            print(f"   {j}) {opt}")
        print()
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    repo = Path(args.path or ".").resolve()
    session = require_session(repo)

    if args.submit and not args.key:
        session = submit_answers(session, session.get("answers") or {})
        save_session(repo, session)
        print("Q&A marked complete. Run: actguard generate report")
        return 0

    answers: dict[str, str] = {}
    if args.key:
        if not args.value:
            print("Error: --value required with --key", file=sys.stderr)
            return 1
        answers[args.key] = args.value
    else:
        for q in list_questions(session):
            opts = q.get("opts")
            prompt = f"\n{q['q']}"
            if q.get("help"):
                prompt += f"\n  ({q['help']})"
            if opts:
                for j, opt in enumerate(opts, 1):
                    prompt += f"\n  {j}) {opt}"
            raw = input(prompt + "\n> ").strip()
            if raw.isdigit() and opts:
                idx = int(raw) - 1
                if 0 <= idx < len(opts):
                    raw = opts[idx]
            answers[q["key"]] = raw

    session = submit_answers(session, answers)
    save_session(repo, session)
    print("Answers saved.")
    if args.submit or not args.key:
        print("Run: actguard generate report")
    return 0


def _validate_lang(lang: str) -> bool:
    from eu_compliance import SUPPORTED_LANGUAGES

    return lang in SUPPORTED_LANGUAGES


def _resolve_langs(primary: str, secondary: str | None) -> list[str] | None:
    if not _validate_lang(primary):
        print(f"Error: unsupported language {primary!r}", file=sys.stderr)
        return None
    langs = [primary]
    if secondary:
        if not _validate_lang(secondary):
            print(f"Error: unsupported language {secondary!r}", file=sys.stderr)
            return None
        langs.append(secondary)
    return langs


def _run_generate(args: argparse.Namespace, artifact: str) -> int:
    from actguard.generate import ARTIFACT_CHOICES, generate_artifact, generate_all_artifacts

    if artifact not in ARTIFACT_CHOICES:
        print(f"Error: unknown artifact {artifact!r}", file=sys.stderr)
        return 1

    repo = Path(args.path or ".").resolve()
    session = require_session(repo)

    if artifact != "extras" and not session.get("qa_submitted"):
        print("Error: complete Q&A first (actguard answer)", file=sys.stderr)
        return 1

    langs = _resolve_langs(args.lang, getattr(args, "secondary_lang", None))
    if langs is None:
        return 1

    project = session.get("project_name") or repo.name
    labels = {
        "report": "compliance report",
        "implement": "implementation guide + agent prompt",
        "rollout": "rollout guide",
        "privacy": "privacy policy draft",
        "tos": "terms of service draft",
        "extras": "founder extras",
        "all": "full compliance plan",
    }
    print(f"Generating {labels.get(artifact, artifact)} for {project}…")
    if artifact != "extras":
        print(f"  Language: {', '.join(langs)}")
    print("  Uses your LLM API key. Output is markdown only.\n")

    try:
        if artifact == "all":
            saved = generate_all_artifacts(
                repo,
                session,
                langs,
                progress=_progress,
            )
        else:
            saved = []
            multi = len(langs) > 1
            for lang in langs:
                saved.extend(
                    generate_artifact(
                        artifact,
                        repo,
                        session,
                        lang,
                        multi_lang=multi,
                        progress=_progress,
                    )
                )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\n✓ Saved:")
    for path in saved:
        print(f"  {path}")
    if artifact in ("implement", "all"):
        print("\nNext: actguard fix --next --dry-run")
    elif artifact == "report":
        print("\nNext: actguard generate implement")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    return _run_generate(args, args.artifact)


def cmd_plan(args: argparse.Namespace) -> int:
    return _run_generate(args, "all")


def cmd_report(args: argparse.Namespace) -> int:
    return _run_generate(args, "report")


def cmd_fix(args: argparse.Namespace) -> int:
    from actguard.agent.fix import run_fix

    repo = Path(args.path or ".").resolve()

    if not args.next and not args.task:
        print("Error: specify --next or --task P0|P1|…", file=sys.stderr)
        return 1

    try:
        result = run_fix(
            repo,
            dry_run=args.dry_run,
            yes=args.yes,
            interactive=not args.yes and not args.dry_run,
            task_prefix=args.task,
            use_next=args.next or bool(args.task),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(result.message)
    return 0 if result.applied or args.dry_run else 0


def cmd_status(args: argparse.Namespace) -> int:
    import platform as _platform

    repo = Path(args.path or ".").resolve()
    sess_path = session_path(repo)

    print("ActGuard Status")
    print("=" * 40)
    print(f"Version: {__version__}")
    print(f"Platform: {_platform.system()} {_platform.machine()}")
    print(f"LLM: {llm_status_line()}")

    chroma = chroma_dir()
    if chroma.is_dir() and any(chroma.iterdir()):
        print(f"RAG index: ✓ ({dir_size_mb(chroma)}MB)")
    else:
        print("RAG index: ✗ Not found (run: actguard setup)")

    if sess_path.is_file():
        session = load_session(repo)
        print(f"\nSession: ✓ {sess_path}")
        if session:
            print(f"  Project: {session.get('project_name', '?')}")
            print(f"  Q&A complete: {session.get('qa_submitted', False)}")
            readiness = session.get("readiness") or {}
            if readiness.get("final_overall") is not None:
                print(f"  Readiness: {readiness['final_overall']}/100")
    else:
        print("\nSession: none (run actguard scan)")

    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    from mcp_server.server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="actguard",
        description="ActGuard — local EU compliance CLI (scan, generate, fix)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Build RAG index and check LLM config").set_defaults(
        func=cmd_setup
    )

    p_scan = sub.add_parser("scan", help="Scan a project directory locally")
    p_scan.add_argument("path", nargs="?", default=".", help="Project path")
    p_scan.add_argument("--fast", action="store_true", help="Skip LLM readiness review")
    p_scan.set_defaults(func=cmd_scan)

    p_q = sub.add_parser("questions", help="Show Q&A questions")
    p_q.add_argument("path", nargs="?", default=".", help="Project path")
    p_q.set_defaults(func=cmd_questions)

    p_a = sub.add_parser("answer", help="Answer compliance questions")
    p_a.add_argument("path", nargs="?", default=".", help="Project path")
    p_a.add_argument("--key", help="Question key")
    p_a.add_argument("--value", help="Answer value (with --key)")
    p_a.add_argument("--submit", action="store_true", help="Mark Q&A complete")
    p_a.set_defaults(func=cmd_answer)

    from actguard.generate import ARTIFACT_CHOICES

    p_gen = sub.add_parser("generate", help="Generate one markdown artifact (BYOK)")
    p_gen.add_argument("artifact", choices=list(ARTIFACT_CHOICES), help="Artifact type")
    p_gen.add_argument("path", nargs="?", default=".", help="Project path")
    p_gen.add_argument("--lang", default="English", help="Language")
    p_gen.add_argument("--secondary-lang", default=None, help="Optional second language")
    p_gen.set_defaults(func=cmd_generate)

    p_plan = sub.add_parser("plan", help="Generate full plan (alias: generate all)")
    p_plan.add_argument("path", nargs="?", default=".", help="Project path")
    p_plan.add_argument("--lang", default="English", help="Primary language")
    p_plan.add_argument("--secondary-lang", default=None, help="Optional second language")
    p_plan.set_defaults(func=cmd_plan)

    p_fix = sub.add_parser("fix", help="Apply next fix from implementation guide")
    p_fix.add_argument("path", nargs="?", default=".", help="Project path")
    p_fix.add_argument("--next", action="store_true", help="Next actionable task")
    p_fix.add_argument("--task", metavar="P0", help="Tasks with this priority")
    p_fix.add_argument("--dry-run", action="store_true", help="Show diff only")
    p_fix.add_argument("--yes", action="store_true", help="Apply without prompt")
    p_fix.set_defaults(func=cmd_fix)

    p_r = sub.add_parser("report", help="Generate compliance report")
    p_r.add_argument("path", nargs="?", default=".", help="Project path")
    p_r.add_argument("--lang", default="English", help="Report language")
    p_r.add_argument("--secondary-lang", default=None, help="Optional second language")
    p_r.set_defaults(func=cmd_report)

    p_s = sub.add_parser("status", help="Show session and LLM status")
    p_s.add_argument("path", nargs="?", default=".", help="Project path")
    p_s.set_defaults(func=cmd_status)

    sub.add_parser("mcp", help="Run MCP server (stdio, for Cursor)").set_defaults(
        func=cmd_mcp
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
