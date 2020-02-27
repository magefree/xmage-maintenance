#!/usr/bin/env python3

"""Collection of maintenance tools for XMage.

Usage:
  xmage-maintenance [options] full-spoiler <set_code> <spoiler_url>
  xmage-maintenance [options] implemented <card_name> [<set_code>]
  xmage-maintenance [options] implemented-list
  xmage-maintenance [options] implemented-since <revision>
  xmage-maintenance [options] markdown-link <card_name> [<set_code>]
  xmage-maintenance [options] oracle-update <set_code>
  xmage-maintenance [options] total
  xmage-maintenance -h | --help

Options:
  -h, --help     Print this message and exit.
  -p, --pull     Pull master before performing maintenance.
  -v, --verbose  Print progress updates while performing maintenance.
  --patch     When used with the `oracle-update` subcommand, only copy the cards section.
  --stdout    Print to stdout instead of copying to clipboard.
"""

import sys

import collections
import contextlib
import docopt
import html.parser
import io
import itertools
import mtgjson
import os
import pathlib
import re
import requests
import subprocess

MASTER = pathlib.Path(os.environ.get('XMAGE_MASTER', '/opt/git/github.com/magefree/mage/master'))
SET_REFACTOR_1_REV = 'e0b43883612d551873445ace182c5fc433b283d7'
SET_REFACTOR_2_REV = '39eaaf727491e998ba6137a18fcdd18fde95b558'
STAGE = pathlib.Path(os.environ.get('XMAGE_STAGE', '/opt/git/github.com/fenhl/mage/stage'))

OPTIONS = {
    'stdout': False,
    'verbose': False
}

class FullSpoilerParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.div_found = False
        self.card_images = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and attrs.get('class') in ('resizing-cig', 'rtecenter'):
            self.div_found = True
        elif tag == 'img':
            self.handle_startendtag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'div':
            self.div_found = False

    def handle_startendtag(self, tag, attrs):
        attrs = dict(attrs)
        if self.div_found and tag == 'img' and 'src' in attrs and 'alt' in attrs:
            normalized_card_name = re.sub('’', "'", attrs['alt'])
            self.card_images[normalized_card_name] = attrs['src']

def copy(text):
    if OPTIONS['stdout']:
        print(text)
    else:
        subprocess.run(['pbcopy'], input=text.encode('utf-8'))

def implemented(name, expansion=None, *, repo=MASTER):
    for set_class in (repo / 'Mage.Sets' / 'src' / 'mage' / 'sets').iterdir():
        if set_class.is_dir():
            continue
        with set_class.open() as f:
            text = f.read()
        for line in text.split('\n'):
            if expansion is not None:
                match = re.match('        super\\("[^"]+", "([A-Z0-9]+)"', line)
                if match and match.group(1) != expansion:
                    break
            match = re.search('cards.add\\(new SetCardInfo\\("{}",'.format(name), line)
            if match:
                return True
    return False

def iter_implemented(*, repo=MASTER, rev=None):
    if rev is None:
        set_class_files = (
            path
            for path in (repo / 'Mage.Sets' / 'src' / 'mage' / 'sets').iterdir()
            if not path.is_dir()
        )
    elif older_than(repo, rev, SET_REFACTOR_2_REV):
        for set_code, card_name in old_iter_implemented(repo=repo, rev=rev, very_old=older_than(repo, rev, SET_REFACTOR_1_REV)):
            yield set_code, card_name
        return
    else:
        set_class_files = (
            repo / 'Mage.Sets' / 'src' / 'mage' / 'sets' / entry.split('\t', 1)[1]
            for entry in subprocess.run(['git', 'ls-tree', f'{rev}:Mage.Sets/src/mage/sets'], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8', check=True).stdout.splitlines()
            if entry.split(' ', 2)[1] != 'tree'
        )
    for set_class in set_class_files:
        set_code = None
        if rev is None:
            with set_class.open() as f:
                text = f.read()
        else:
            text = subprocess.run(['git', 'show', f'{rev}:{set_class.relative_to(repo)}'], cwd=repo, stdout=subprocess.PIPE, encoding='utf-8', check=True).stdout
        for line in text.split('\n'):
            if set_code is None:
                match = re.match('        super\\("[^"]+", "([A-Z0-9]+)"', line)
                if match:
                    set_code = match.group(1)
            else:
                match = re.search('cards.add\\(new SetCardInfo\\("([^"]+)",', line)
                if match:
                    yield set_code, match.group(1)

def markdown_card_link(name, set_code=None, db=None):
    if db is None:
        db = mtgjson.CardDb.from_url()
    if set_code is None:
        return '[{}](https://mtg.wtf/card?q=%21{})'.format(name, name.replace(' ', '+'))
    try:
        card = db.sets[set_code].cards_by_name[name]
    except KeyError:
        return name
    try:
        url_set_code = db.sets[set_code].magicCardsInfoCode
    except AttributeError:
        url_set_code = set_code
    try:
        number = card.number
    except AttributeError:
        try:
            number = card.mciNumber
        except AttributeError as e:
            return '[{}](https://mtg.wtf/card?q=%21{})'.format(name, name.replace(' ', '+'))
    with contextlib.suppress(ValueError):
        number = int(number)
        if 'Plane' in card.types or 'Phenomenon' in card.types:
            number += 1000
    return '[{}](https://mtg.wtf/card/{}/{})'.format(name, url_set_code.lower(), number)

def old_iter_implemented(rev, *, repo=MASTER, very_old=False):
    if very_old:
        card_class_sets = collections.defaultdict(set)
        set_class_files = (
            repo / 'Mage.Sets' / 'src' / 'mage' / 'sets' / entry.split('\t', 1)[1]
            for entry in subprocess.run(['git', 'ls-tree', f'{rev}:Mage.Sets/src/mage/sets'], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8', check=True).stdout.splitlines()
            if entry.split(' ', 2)[1] != 'tree'
        )
        for set_class in set_class_files:
            if set_class.stem == 'Sets':
                continue
            set_code = {
                'AlaraReborn': 'ARB',
                'Conflux': 'CON',
                'Magic2010': 'M10',
                'Magic2011': 'M11',
                'Planechase': 'HOP',
                'RiseOfTheEldrazi': 'ROE',
                'ShardsOfAlara': 'ALA',
                'Tenth': '10E',
                'Worldwake': 'WWK',
                'Zendikar': 'ZEN'
            }[set_class.stem]
            text = subprocess.run(['git', 'show', f'{rev}:{set_class.relative_to(repo)}'], cwd=repo, stdout=subprocess.PIPE, encoding='utf-8', check=True).stdout
            for line in text.split('\n'):
                match = re.match('import mage\\.sets\\.([0-9a-z]+)\\.\\*;', line)
                if match:
                    class_set = match.group(1)
                match = re.match('\\s*this\\.cards\\.add\\(([0-9A-Za-z]+)\\.class\\);', line)
                if match:
                    card_class_sets[class_set, match.group(1)].add(set_code)
    try:
        card_class_files = (
            repo / 'Mage.Sets' / 'src' / 'mage' / 'sets' / set_entry.split('\t', 1)[1] / card_entry.split('\t', 1)[1]
            for set_entry in subprocess.run(['git', 'ls-tree', f'{rev}:Mage.Sets/src/mage/sets'], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8', check=True).stdout.splitlines()
            if set_entry.split(' ', 2)[1] == 'tree' and set_entry.split('\t', 1)[1] != 'tokens'
            for card_entry in subprocess.run(['git', 'ls-tree', '{}:Mage.Sets/src/mage/sets/{}'.format(rev, set_entry.split('\t', 1)[1])], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding='utf-8', check=True).stdout.splitlines()
            if card_entry.split(' ', 2)[1] != 'tree'
        )
    except subprocess.CalledProcessError: # listing sets fails on the very first few commits because Mage.Sets/src/mage/sets doesn't exist yet
        return
    classes_cards_map = {}
    reprints = {}
    for card in card_class_files:
        text = subprocess.run(['git', 'show', f'{rev}:{card.relative_to(repo)}'], cwd=repo, stdout=subprocess.PIPE, encoding='utf-8', errors='replace', check=True).stdout
        set_code = superclass_set = superclass_name = card_name = None
        imports = {}
        for line in text.split('\n'):
            match = re.match('import mage\\.sets\\.([0-9a-z]+)\\.([0-9A-Za-z]+);', line)
            if match:
                imports[match.group(2)] = match.group(1)
            match = re.match('public class [0-9A-Za-z]+ extends (?:mage\\.cards\\.basiclands\\.)?(Plains|Island|Swamp|Mountain|Forest)(?:<[0-9A-Za-z]+>)?\\s*\\{', line)
            if match:
                superclass_name = card_name = match.group(1)
            match = re.match('public class [0-9A-Za-z]+ extends mage\\.sets\\.([0-9a-z]+)\\.([0-9A-Za-z]+)\\s*\\{', line)
            if match:
                superclass_set, superclass_name = match.groups()
            match = re.match('public class [0-9A-Za-z]+ extends ([0-9A-Za-z]+)\\s*\\{', line)
            if match and match.group(1) in imports:
                superclass_name = match.group(1)
                superclass_set = imports[match.group(1)]
            match = re.match('\\s*super\\([A-Za-z]+,\\s*(?:[0-9]+,)?\\s*"(.+?)",', line)
            if match:
                card_name = match.group(1)
            match = re.match('\\s*this\\.expansionSetCode = "([0-9A-Z]+)";', line)
            if match:
                set_code = match.group(1)
                break
        if set_code is not None and card_name is not None:
            classes_cards_map[card.parent.name, card.stem] = set_code, card_name
            yield set_code, card_name
        elif superclass_set is not None and superclass_name is not None:
            reprints[card.parent.name, card.stem] = superclass_set, superclass_name, set_code
        elif very_old and card_name is not None:
            for set_code in card_class_sets[card.parent.name, card.stem]:
                yield set_code, card_name
        else:
            if OPTIONS['verbose']:
                print(f'Neither set/name nor superclass found for {rev}:{card}')
            continue
    if not very_old:
        for superclass_set, superclass_name, set_code in reprints.values():
            while (superclass_set, superclass_name) in reprints:
                superclass_set, superclass_name, super_set_code = reprints[superclass_set, superclass_name]
                if set_code is None:
                    set_code = super_set_code
            if set_code is None:
                yield classes_cards_map[superclass_set, superclass_name]
            else:
                yield set_code, classes_cards_map[superclass_set, superclass_name][1]

def older_than(repo, rev1, rev2):
    return subprocess.run(['git', 'merge-base', rev1, rev2], cwd=repo, stdout=subprocess.PIPE, encoding='utf-8', check=True).stdout.strip() != rev2

if __name__ == '__main__':
    arguments = docopt.docopt(__doc__)
    if arguments['--verbose']:
        import blessings

        term = blessings.Terminal()
        OPTIONS['verbose'] = True
    if arguments['--stdout']:
        OPTIONS['stdout'] = True
    if arguments['--pull']:
        subprocess.run(['git', 'pull'], cwd=str(MASTER))
    if arguments['full-spoiler']:
        if OPTIONS['verbose']:
            print('[....] downloading MTG JSON', end='', flush=True)
        db = mtgjson.CardDb.from_url()
        if OPTIONS['verbose']:
            print('\r[ ok ]')
            print('[....] parsing full spoiler', end='', flush=True)
        full_spoiler = requests.get(arguments['<spoiler_url>']).text
        if OPTIONS['verbose']:
            print('\r[====]', end='', flush=True)
        full_spoiler_parser = FullSpoilerParser()
        full_spoiler_parser.feed(full_spoiler)
        card_images = full_spoiler_parser.card_images
        if OPTIONS['verbose']:
            print('\r[ ok ]')
        reprints = []
        new_cards = []
        num_cards = len(card_images)
        for i, (name, image) in enumerate(sorted(card_images.items())):
            if OPTIONS['verbose']:
                progress = int(5 * i / num_cards)
                print('\r[{}{}] checking for implemented cards'.format('=' * progress, '.' * (4 - progress)), end='', flush=True)
            if name in db.cards_by_name:
                collection = reprints
            elif ' // ' in name and all(part_name in db.cards_by_name for part_name in name.split(' // ')):
                collection = reprints
            else:
                collection = new_cards
            collection.append('- [{}] [{}]({})'.format('x' if implemented(name, arguments['<set_code>']) else ' ', name, image))
        if OPTIONS['verbose']:
            print('\r[ ok ]')
        if OPTIONS['stdout']:
            print('[ ** ] reprints')
        copy('\n'.join(reprints))
        if OPTIONS['stdout']:
            print('[ ** ] new cards')
        else:
            input('[ ** ] reprints copied to clipboard, press return to copy new cards')
        copy('\n'.join(new_cards))
        if not OPTIONS['stdout']:
            print('[ ** ] new cards copied to clipboard')
    elif arguments['implemented']:
        impl = implemented(arguments['<card_name>'], expansion=arguments['<set_code>'])
        if OPTIONS['verbose']:
            print('[{}] {}{}'.format(' ok ' if impl else 'FAIL', '({}) '.format(arguments['<set_code>']) if arguments['<set_code>'] else '', arguments['<card_name>']))
        sys.exit(0 if impl else 1)
    elif arguments['implemented-list']:
        if OPTIONS['verbose']:
            print('[....] determining current implemented cards', end='', flush=True, file=sys.stderr)
        current_implemented = {card_name for set_code, card_name in iter_implemented()}
        if OPTIONS['verbose']:
            print('\r[ ok ]', file=sys.stderr)
        for card_name in sorted(current_implemented):
            print(card_name)
    elif arguments['implemented-since']:
        try:
            if OPTIONS['verbose']:
                print('[....] downloading MTG JSON', end='', flush=True)
            db = mtgjson.CardDb.from_url()
            if OPTIONS['verbose']:
                print('\r[ ok ]')
                print('[....] determining current implemented cards', end='', flush=True)
            current_implemented = collections.defaultdict(set)
            for set_code, card_name in iter_implemented():
                current_implemented[set_code].add(card_name)
            if OPTIONS['verbose']:
                print('\r[ ok ]')
                print('[....] determining implemented cards as of given revision', end='', flush=True)
            subprocess.check_call(['git', 'checkout', arguments['<revision>']], cwd=str(MASTER), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for set_code, card_name in iter_implemented():
                current_implemented[set_code].discard(card_name)
            if OPTIONS['verbose']:
                print('\r[ ok ]')
                print('[....] formatting', end='', flush=True)
            output = []
            for i, (set_code, set_implemented) in enumerate(sorted(current_implemented.items())):
                if OPTIONS['verbose']:
                    progress = int(5 * i / len(current_implemented))
                    print('\r[{}{}]'.format('=' * progress, '.' * (4 - progress)), end='', flush=True)
                if len(set_implemented) > 0:
                    output.append('* {}: {}'.format(set_code, '; '.join(markdown_card_link(card_name, set_code, db=db) for card_name in sorted(set_implemented))))
            if OPTIONS['verbose']:
                print('\r[ ok ]')
            if len(output) > 0:
                copy('\n'.join(output))
                if OPTIONS['verbose'] and not OPTIONS['stdout']:
                    print('[ ** ] new cards copied to clipboard')
            else:
                if OPTIONS['verbose']:
                    print('[ ** ] no new cards')
        finally:
            subprocess.check_call(['git', 'checkout', 'master'], cwd=str(MASTER), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif arguments['markdown-link']:
        if OPTIONS['verbose']:
            print('[....] downloading MTG JSON', end='', flush=True)
        db = mtgjson.CardDb.from_url()
        if OPTIONS['verbose']:
            print('\r[ ok ]')
        print(markdown_card_link(arguments['<card_name>'], arguments['<set_code>'], db=db))
    elif arguments['oracle-update']:
        set_code = arguments['<set_code>']
        if OPTIONS['verbose']:
            print('[....] downloading MTG JSON', end='', flush=True)
        db = mtgjson.CardDb.from_url(mtgjson.ALL_SETS_X_ZIP_URL)
        if OPTIONS['verbose']:
            print('\r[ ok ]')
        reprints = []
        new_cards = []
        num_cards = len(db.sets[set_code].cards_by_name.items())
        for i, (name, card) in enumerate(sorted(db.sets[set_code].cards_by_name.items())):
            if OPTIONS['verbose']:
                progress = int(5 * i / num_cards)
                print('\r[{}{}] checking for implemented cards'.format('=' * progress, '.' * (4 - progress)), end='', flush=True)
            (reprints if len(card.printings) > 1 else new_cards).append('- [{}] {}'.format('x' if implemented(name, expansion=set_code) else ' ', markdown_card_link(name, set_code, db=db)))
        if OPTIONS['verbose']:
            print('\r[ ok ]')
        copy(('' if arguments['--patch'] else """\
# Rules

The following rules changes from {set_code} may be relevant for XMage:

**TODO**

# Oracle

In {set_code}, there have been the following Oracle changes which will have to be implemented. Functional errata are marked in boldface, and unimplemented cards are omitted.

## Multiple cards

**TODO**

## Single card

**TODO**

""".format(set_code=set_code)) + """# Cards

The following cards have been printed in {set_code} and will have to be implemented.

## Reprints

{reprints}

## New cards

{new_cards}
""".format(reprints='\n'.join(reprints), new_cards='\n'.join(new_cards), set_code=set_code))
        print('[ ** ] text copied to clipboard')
    elif arguments['total']:
        cards = collections.defaultdict(lambda: 0)
        for set_dir in (MASTER / 'Mage.Sets' / 'src' / 'mage' / 'sets').iterdir():
            if not set_dir.is_dir():
                continue
            for card in set_dir.iterdir():
                if card.is_dir():
                    continue
                cards[card.name] += 1
        print('{} unique, {} total'.format(len(cards), sum(cards.values())))
    else:
        sys.exit('xmage-maintenance: subcommand not implemented')
