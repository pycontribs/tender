#!/usr/bin/env python
"""CLI Interface of Tender"""
from tender import __version__
from blessings import Terminal
from copy import deepcopy
import click
from click_help_colors import HelpColorsGroup, HelpColorsCommand, version_option
import giturlparse
import json
import logging
import os
import sys
from types import SimpleNamespace

import git
from github import Github
import yaml

term = Terminal()

_logger = logging.getLogger(__name__)


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
            _logger.warning("Config file %s not found, defaulting to empty.", config_file)
            return {}


class Tender:
    def __init__(self, org, repo):
        self.cfg = Config()
        self.repo_name = repo
        self.org_name = org
        token = os.environ.get("HOMEBREW_GITHUB_API_TOKEN")
        self.github = Github(login_or_token=token)
        self.repo = self.github.get_repo(f"{org}/{repo}")
        self.pulls = self.repo.get_pulls(state="all")

        # required_labels is a list of labels from which at least one needs to
        # be present on each PR, and only one.
        self.required_labels = set()
        if self.cfg.release_drafter["exclude-labels"]:
            self.required_labels.update(self.cfg.release_drafter["exclude-labels"])
        for category in self.cfg.release_drafter["categories"]:
            if "labels" in category:
                self.required_labels.update(category["labels"])
            else:
                _logger.warning("%s category does not have any labels defined.", category)

    def do_pulls(self):
        _logger.info("Auditing pull-requests")
        cnt = 0
        for pull in self.pulls:
            if cnt > 20:
                sys.exit(1)
            if not pull.is_merged() and pull.state == "closed":
                continue
            msg = "{}: [{}] {}".format(
                link(pull.html_url, "PR #{}".format(pull.number)), pull.state, pull.title
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
                if label.color != cfg_label.color or label.description != cfg_label.description:
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
    version=__version__, prog_name="tender", version_color="green", prog_name_color="yellow"
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
        ctx.invoke(pulls)
        ctx.invoke(labels)


@cli.command(cls=HelpColorsCommand)
@click.pass_context
def pulls(ctx):
    ctx.obj["app"].do_pulls()


@cli.command(cls=HelpColorsCommand)
@click.pass_context
def labels(ctx):
    ctx.obj["app"].do_labels()


if __name__ == "__main__":

    cli()  # pylint: disable=no-value-for-parameter
