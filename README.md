![PyPI](https://img.shields.io/pypi/v/tender)
![PyPI - License](https://img.shields.io/pypi/l/tender)
![build](https://github.com/pycontribs/tender/workflows/tox/badge.svg)

# About

`Tender` aims to **ease maintenance** of github open-source
projects by reducing the amount of boring tasks.

Please note that the project is in its early stages of development and is not
yet ready for production use. Still, feel free to look at it, maybe you can
join us and avoid writing your own tool that aims to do the same.

Try running `tender` on your repository because by default it
will no do any modifycation.

Tender can be used manually as a command-line tool or on CI/CD pipelines, like
github actions.

Example of activities performed:

- assure **required labels** are used on pull-requests
- create and update **release notes** based on merged pull-requests
- maintain a list of standardized labels

## Usage

![screenshot](https://sbarnea.com/ss/Screen-Shot-2020-08-16-21-23-29.23.png)

## Background

The project was inspired by existing tools like:

- [Release Drafter](https://github.com/marketplace/actions/release-drafter) --
  compatible configuration
- [GitHub Labeler](https://github.com/marketplace/actions/github-labeler) --
  compatible configuration

Because these tools had very limited use and almost never had a dual mode
command line and github action, we decided to create one that can take care of
all tasks related to maintenance of open-source projects, one that can
optionally keep configuration in a single place, a meta repository.
