"""Plan source-bound public releases and validate Conventional Commit messages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import tomlkit
from git import Repo
from semantic_release.commit_parser.conventional.options import (
    ConventionalCommitParserOptions,
)
from semantic_release.commit_parser.conventional.parser import ConventionalCommitParser
from semantic_release.commit_parser.token import ParseError
from semantic_release.errors import InvalidVersion
from semantic_release.version.algorithm import next_version, tags_and_versions
from semantic_release.version.translator import VersionTranslator


STABLE_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
INITIAL_VERSION = "0.1.0"
BASELINE_COMMIT = "ccad1d7fcde045ff05aca143e0d072b517d4b972"


class ReleasePlanError(RuntimeError):
    pass


def configuration(root: Path) -> tuple[dict, dict]:
    document = tomlkit.parse((root / "pyproject.toml").read_text()).unwrap()
    tools = document.get("tool", {})
    semantic = tools.get("semantic_release", {})
    if semantic.get("commit_parser", "conventional") != "conventional":
        raise ReleasePlanError("release planning requires the conventional parser")
    return semantic, tools.get("trame_vtkjs", {}).get("release", {})


def parser_for(config: dict) -> ConventionalCommitParser:
    return ConventionalCommitParser(
        ConventionalCommitParserOptions(**config.get("commit_parser_options", {}))
    )


def public_version(value: str) -> str:
    if not STABLE_VERSION.fullmatch(value):
        raise ReleasePlanError(f"expected a stable X.Y.Z version, got {value!r}")
    return value


def plan(root: Path) -> dict:
    semantic, product = configuration(root)
    initial = public_version(product.get("initial_version", INITIAL_VERSION))
    translator = VersionTranslator(
        tag_format=semantic.get("tag_format", "trame-vtkjs-v{version}")
    )
    with Repo(root) as repo:
        if repo.is_dirty(untracked_files=True):
            raise ReleasePlanError("release planning requires committed source")
        head = repo.head.commit
        baseline = repo.commit(product.get("baseline_commit", BASELINE_COMMIT))
        if not repo.is_ancestor(baseline, head):
            raise ReleasePlanError(
                "product release baseline is not an ancestor of HEAD"
            )
        product_commits = {
            commit.hexsha
            for commit in repo.iter_commits(f"{baseline.hexsha}..{head.hexsha}")
        }
        matching = []
        for tag in repo.tags:
            try:
                version = translator.from_tag(tag.name)
            except InvalidVersion as error:
                raise ReleasePlanError(
                    f"invalid product release tag {tag.name}"
                ) from error
            if version is not None:
                public_version(str(version))
                matching.append(tag)
        reachable = [
            (tag, version)
            for tag, version in tags_and_versions(matching, translator)
            if repo.is_ancestor(baseline, tag.commit)
            and repo.is_ancestor(tag.commit, head)
        ]
        at_head = [(tag, version) for tag, version in reachable if tag.commit == head]
        if len(at_head) > 1:
            raise ReleasePlanError("multiple product release versions identify HEAD")
        previous = next(
            ((tag, version) for tag, version in reachable if tag.commit != head), None
        )
        if at_head:
            tag, version = at_head[0]
            if previous and version <= previous[1]:
                raise ReleasePlanError(
                    "release versions must increase along product history"
                )
            release = True
            version_text = str(version)
            tag_name = tag.name
        else:
            previous = reachable[0] if reachable else None
            # The pinned algorithm reads only tags and the branch's head commit.
            # Supplying that read-only view also handles detached CI checkouts.
            history = SimpleNamespace(
                tags=matching, active_branch=SimpleNamespace(commit=head)
            )
            conventional = parser_for(semantic)
            product_parser = SimpleNamespace(
                parse=lambda commit: (
                    conventional.parse(commit)
                    if commit.hexsha in product_commits
                    else ParseError(
                        commit, "commit predates the product release baseline"
                    )
                )
            )
            version = next_version(
                repo=history,
                translator=translator,
                commit_parser=product_parser,
                allow_zero_version=semantic.get("allow_zero_version", True),
                major_on_zero=semantic.get("major_on_zero", False),
                prerelease=False,
            )
            release = str(version) != (
                str(previous[1]) if previous is not None else "0.0.0"
            )
            if (
                release
                and previous is None
                and version < translator.from_string(initial)
            ):
                version = translator.from_string(initial)
            version_text = public_version(str(version)) if release else ""
            tag_name = translator.str_to_tag(version_text) if release else ""
            if release and any(tag.name == tag_name for tag in matching):
                raise ReleasePlanError(
                    f"release tag {tag_name} belongs to another source commit"
                )
        return {
            "commit": head.hexsha,
            "tree": head.tree.hexsha,
            "release": release,
            "version": version_text,
            "tag": tag_name,
            "previousTag": previous[0].name if previous else None,
            "previousCommit": previous[0].commit.hexsha if previous else None,
        }


def check(root: Path, expected: dict) -> None:
    actual = plan(root)
    if actual != expected:
        changes = [name for name in actual if actual[name] != expected.get(name)]
        raise ReleasePlanError("stale release plan: " + ", ".join(changes))


def lint_message(message: str, parser: ConventionalCommitParser) -> None:
    subject = message.splitlines()[0] if message.splitlines() else ""
    parsed = parser.parse_message(message)
    if (
        parsed is None
        or parser.commit_subject.fullmatch(subject) is None
        or not parsed.descriptions
        or not parsed.descriptions[0].strip()
    ):
        raise ReleasePlanError(
            "expected a Conventional Commit type(scope): description"
        )


def lint_commits(root: Path, base: str | None, head: str = "HEAD") -> int:
    semantic, product = configuration(root)
    parser = parser_for(semantic)
    with Repo(root) as repo:
        baseline = repo.commit(product.get("baseline_commit", BASELINE_COMMIT))
        start, end = repo.commit(base) if base else baseline, repo.commit(head)
        ancestors = repo.merge_base(start, end)
        if not ancestors:
            raise ReleasePlanError("commit validation base has unrelated history")
        if not repo.is_ancestor(baseline, end):
            raise ReleasePlanError(
                "product release baseline is not an ancestor of HEAD"
            )
        if not repo.is_ancestor(start, end):
            start = ancestors[0]
        if repo.is_ancestor(start, baseline):
            start = baseline
        commits = list(
            repo.iter_commits(f"{start.hexsha}..{end.hexsha}", no_merges=True)
        )
        errors = []
        for commit in commits:
            try:
                lint_message(commit.message, parser)
            except ReleasePlanError as error:
                errors.append(f"{commit.hexsha[:7]}: {error}")
        if errors:
            raise ReleasePlanError("invalid commit messages:\n" + "\n".join(errors))
    return len(commits)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("plan")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--github-output", type=Path)
    verify = subparsers.add_parser("check")
    verify.add_argument("--plan", type=Path, required=True)
    lint = subparsers.add_parser("lint")
    lint.add_argument("--base")
    lint.add_argument("--head", default="HEAD")
    lint.add_argument("--message-file", type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.command == "plan":
            result = plan(root)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            if args.github_output:
                with args.github_output.open("a") as stream:
                    stream.write(f"release={str(result['release']).lower()}\n")
                    stream.write(f"version={result['version']}\n")
                    stream.write(f"tag={result['tag']}\n")
            print(json.dumps(result, sort_keys=True))
        elif args.command == "check":
            check(root, json.loads(args.plan.read_text()))
            print("Release plan matches the source and release history")
        elif args.message_file:
            semantic, _ = configuration(root)
            lint_message(args.message_file.read_text(), parser_for(semantic))
        else:
            count = lint_commits(root, args.base, args.head)
            print(f"Validated {count} Conventional Commit messages")
    except (ReleasePlanError, OSError, ValueError) as error:
        sys.exit(f"release_plan: ERROR: {error}")


if __name__ == "__main__":
    main()
