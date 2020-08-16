#!/usr/bin/env python
"""CLI Interface of Tender tool"""
import datetime
import json
import logging
import os
import sys
from copy import deepcopy
from types import SimpleNamespace
from typing import Dict, List, Optional

import click
import git
import github
import giturlparse
import humanize
import yaml
from blessings import Terminal
from click_help_colors import HelpColorsCommand, HelpColorsGroup, version_option
from packaging.version import parse as parse_version

from tender import __version__

term = Terminal()

_logger = logging.getLogger(__name__)
DEFAULT_EXCLUDE_LABELS = {"skip-changelog"}


def link(url, name):
    """Print clickabl link on supporting terminals."""
    return "\033]8;;{}\033\\{}\033]8;;\033\\".format(url, name)


def nested_dict_to_namespaces(dic):
    """Code for recursively converting dictionaries of dictionaries
        into SimpleNamespaces instead.
    """

    def recurse(dic):
        if not isinstance(dic, dict):
            return dic
        for key, val in list(dic.items()):
            dic[key] = recurse(val)
        return SimpleNamespace(**dic)

    if not isinstance(dic, dict):
        raise TypeError(f"{dic} is not a dict")

    new_dic = deepcopy(dic)
    return recurse(new_dic)


class Config(SimpleNamespace):
    """Config."""

    def __init__(self):
        self.labels = {}
        for label in self.load_config(".github/labels.yml"):
            self.labels[label["name"]] = SimpleNamespace(
                color=label["color"], description=label["description"]
            )
        self.release_drafter = self.load_config(".github/release-drafter.yml")

    @classmethod
    def load_config(cls, config_file):
        config_file = os.path.expanduser(config_file)
        try:
            with open(config_file, "r") as stream:
                try:
                    return yaml.safe_load(stream)
                except yaml.YAMLError as exc:
                    _logger.error(exc)
                    sys.exit(2)
        except FileNotFoundError:
            _logger.warning(
                "Config file %s not found, defaulting to empty.", config_file
            )
            return {}


class Tender:

    # pylint: disable=too-many-instance-attributes

    def __init__(self, org, repo):
        self.cfg = Config()
        self.git = git.Repo(".")
        self.repo_name = repo
        self.org_name = org
        token = os.environ.get("HOMEBREW_GITHUB_API_TOKEN")
        self.github = github.Github(login_or_token=token)
        self.repo = self.github.get_repo(f"{org}/{repo}")
        self.pulls = self.repo.get_pulls(state="all")
        self.required_labels = set()
        self.errors = []

        # required_labels is a list of labels from which at least one needs to
        # be present on each PR, and only one.

        self.exclude_labels = set(
            self.cfg.release_drafter.get("exclude-labels", DEFAULT_EXCLUDE_LABELS)
        )

        self.label_section_map = dict()
        for category in self.cfg.release_drafter["categories"]:
            if "labels" in category:
                # self.required_labels.union(set(category["labels"]))
                for label in category["labels"]:
                    if label not in self.required_labels:
                        self.required_labels.add(label)
                    if label not in self.label_section_map:
                        self.label_section_map[label] = category["title"]
            else:
                _logger.warning(
                    "%s category does not have any labels defined.", category
                )
        _logger.info(
            "Labels mapped to release notes sections: %s",
            ", ".join(self.label_section_map.keys()),
        )

    def get_last_unreleased_tag(self) -> Optional[git.Tag]:
        for tag in sorted(
            self.git.tags, key=lambda t: t.commit.committed_datetime, reverse=True
        ):
            version = parse_version(str(tag))
            if not version.is_prerelease:
                _logger.info("Last non-prerelease tag was %s", version)
                return tag
        return None

    def get_unreleased_commits(self) -> Dict[str, git.objects.commit.Commit]:
        """Return list of commits since last *release* tag."""
        result = {}
        tag = self.get_last_unreleased_tag()
        tagmap: Dict[str, List] = {}
        for _ in self.git.tags:
            tagmap.setdefault(self.git.commit(_), []).append(_)
        # print(tagmap)
        rev = f"{tag}..HEAD"
        _logger.info("Looking for commits in %s range", rev)
        for commit in self.git.iter_commits(rev=rev):
            result[commit.hexsha] = commit
        return result

    def get_section_for_label(self, label):
        return self.label_section_map[label]

    def do_pulls(self):
        _logger.info("Auditing pull-requests")
        cnt = 0
        for pull in self.pulls:
            if cnt > 20:
                sys.exit(1)
            if not pull.is_merged() and pull.state == "closed":
                continue
            msg = "{}: [{}] {}".format(
                link(pull.html_url, "PR #{}".format(pull.number)),
                pull.state,
                pull.title,
            )
            pr_labels = [p.name for p in pull.get_labels()]
            if len(self.required_labels.intersection(pr_labels)) == 0:
                msg += "\n\tShould have at least one label out of {} but found: {}".format(
                    ", ".join(self.required_labels), ", ".join(pr_labels)
                )
                print(msg)
                cnt += 1
                continue
            if pull.is_merged():
                pass

    def do_labels(self):

        _logger.info("Auditing repository labels")
        _logger.debug(self.cfg.labels)
        existing_labels = [x.name for x in self.repo.get_labels()]
        for label, value in self.cfg.labels.items():
            if label not in existing_labels:
                _logger.warning("Adding label '%s'", label)
                self.repo.create_label(label, value.color, value.description)
        for label in self.repo.get_labels():
            if label.name in self.cfg.labels:
                cfg_label = self.cfg.labels[label.name]
                if (
                    label.color != cfg_label.color
                    or label.description != cfg_label.description
                ):
                    _logger.warning("Updating label '%s' attributes", label.name)
                    label.update(
                        label.name,
                        self.cfg.labels[label.name].color,
                        self.cfg.labels[label.name].description,
                    )
            else:
                _logger.error(
                    "Unknown label '%s' found defined, you may want to rename or remove.",
                    label.name,
                )

    def do_draft(self):
        _logger.info("Draft release notes")

        for release in self.repo.get_releases():
            print(
                f"tag_name={release.tag_name} name={release.title} draft={release.draft}"
                f" prerelease={release.prerelease}"
            )
            if release.draft:
                break

        body = "## Changes\n\n"

        commits = self.get_unreleased_commits()
        sections = {
            category["title"]: "" for category in self.cfg.release_drafter["categories"]
        }

        tag = self.get_last_unreleased_tag()
        no_older_than = datetime.datetime.fromtimestamp(tag.commit.committed_date)

        age = humanize.naturaltime(datetime.datetime.now() - no_older_than)
        _logger.info(
            "Counting %s commits since %s tag, made over %s.", len(commits), tag, age
        )

        for pull in self.repo.get_pulls(state="closed"):

            if pull.merged:

                # ignoring commits
                labels = {x.name for x in pull.labels}
                if not self.exclude_labels.isdisjoint(labels):
                    continue

                if pull.merge_commit_sha in commits:

                    valid_labels = list(self.required_labels.intersection(labels))
                    if valid_labels:
                        section = self.label_section_map[valid_labels[0]]
                        sections[section] = (
                            f"{sections[section]}* {pull.title} (#{pull.number}) "
                            f"@{pull.user.login}\n"
                        )
                    else:
                        self.errors.append(
                            "%s containes unknown labels %s, add one required labels %s."
                            % (
                                link(pull.html_url, "PR #{}".format(pull.number)),
                                labels,
                                self.required_labels,
                            )
                        )
                elif pull.closed_at > no_older_than:
                    print(pull.closed_at, no_older_than)
                    _logger.warning(
                        "Ignored %s because its commit %s was not found among unreleased commits.",
                        pull.html_url,
                        pull.merge_commit_sha,
                    )
                else:
                    _logger.info(
                        "Stopped processing PRs as we encounted first "
                        "one merged before cutoff date."
                    )
                    break

        for section, content in sections.items():
            if content:
                body += f"### {section}\n\n{content}\n"

        release = None
        print(body)


def parsed(result):
    result.raise_for_status()

    if hasattr(result, "text") and result.text[:4] == ")]}'":
        return json.loads(result.text[5:])

    print("ERROR: %s " % (result.result_code))
    sys.exit(1)


@click.group(
    invoke_without_command=True,
    cls=HelpColorsGroup,
    help_headers_color="yellow",
    help_options_color="green",
)
@click.pass_context
@click.option("--debug", "-d", default=False, help="Debug mode", is_flag=True)
@click.option("--repo", "-r", default=None, help="GitHub Repository")
@click.option("--org", "-o", default=None, help="GitHub Organization")
@version_option(
    version=__version__,
    prog_name="tender",
    version_color="green",
    prog_name_color="yellow",
)
def cli(ctx, debug, repo, org):
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)-8s %(message)s")
    handler.setFormatter(formatter)
    _logger.addHandler(handler)

    if debug:
        _logger.setLevel(level=logging.DEBUG)
    else:
        _logger.setLevel(level=logging.INFO)

    if not org or not repo:
        url = git.repo.base.Repo().remotes.origin.url
        gitrepo = giturlparse.parse(url)
        org = gitrepo.owner
        repo = gitrepo.name
        # it.repo.fun.is_git_dir(".")
        _logger.info("Detected %s/%s from context %s", org, repo, url)

    ctx.ensure_object(dict)
    ctx.obj["app"] = Tender(org=org, repo=repo)

    if ctx.invoked_subcommand is None:
        # ctx.invoke(do_pulls)
        # ctx.invoke(do_labels)
        ctx.invoke(do_draft)

    if len(ctx.obj["app"].errors) != 0:
        for err in ctx.obj["app"].errors:
            print(err)
        sys.exit()


@cli.command(cls=HelpColorsCommand)
@click.pass_context
def do_draft(ctx):
    """Generate release notes."""
    ctx.obj["app"].do_draft()


@cli.command(cls=HelpColorsCommand)
@click.pass_context
def do_pulls(ctx):
    """Audit pull requests."""
    ctx.obj["app"].do_pulls()


@cli.command(cls=HelpColorsCommand)
@click.pass_context
def do_labels(ctx):
    """Check if correct labels are defined in project."""
    ctx.obj["app"].do_labels()


if __name__ == "__main__":

    cli()  # pylint: disable=no-value-for-parameter
