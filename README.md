This is a mainenance script that can perform various maintenance tasks on the [XMage repository](https://github.com/magefree/mage).

By default, the script will look for the repository in `/opt/git/github.com/magefree/mage/master`. A different path can be specified using the environment variable `XMAGE_MASTER`.

# Requirements

* Python (latest version)
* [blessings](https://pypi.python.org/pypi/blessings/) (`--verbose` only)
* [docopt](https://pypi.python.org/pypi/docopt/)
* [mtgjson](https://pypi.python.org/pypi/mtgjson/)

# Subcommands

## `change-set-code`

Syntax: `xmage-maintenance [options] change-set-code <xmage_set_dir> <new_set_code>`

Changes all card files in the set directory named `<xmage_set_dir>` to use the `<new_set_code>`. The location of the repository must be given via environment variable `XMAGE_STAGE`.

## `full-spoiler`

Syntax: `xmage-maintenance [options] full-spoiler <set_code> <spoiler_url>`

Generates text for [the tracking issue](https://github.com/magefree/mage/issues/2215) from a full set spoiler released on [magic.wizards.com](https://magic.wizards.com/) and copies it to clipboard.

## `implemented`

Syntax: `xmage-maintenance [options] implemented <card_name> [<set_code>]`

Exits with code 0 if the card named `<card_name>` is implemented, and with a nonzero exit code if it's not. The argument `<set_code>` can optionally be used to look for the card in a specific set.

## `oracle-update`

Syntax: `xmage-maintenance [options] oracle-update <set_code>`

Generates the text for a new [tracking issue](https://github.com/magefree/mage/labels/tracking) and copies it to clipboard. Can only be used with sets that are already in the [MTG JSON](https://mtgjson.com/) database. The sections for rules and Oracle changes must be written manually, [yawgatog.com](http://www.yawgatog.com/resources/) can be used as a source. Use `--patch` to update an existing tracking issue (this will only copy the section “Cards”).

## `total`

Syntax: `xmage-maintenance [options] total`

Counts and prints the number of implemented cards, both unique and total. “Unique” means cards with different names, while “total” counts each printing of each card separately.

# Options

* `--pull` will pull the repository before running the subcommand.
* `--stdout` will print everything to the standard output that would otherwise be copied to clipboard.
* `--verbose` will cause most subcommands to print progress indicators while they are running.
