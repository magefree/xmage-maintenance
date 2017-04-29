#!/usr/bin/env python3

"""Collection of maintenance tools for XMage.

Usage:
  xmage-maintenance [options] full-spoiler <set_code> <spoiler_url>
  xmage-maintenance [options] implemented <card_name> [<set_code>]
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

MASTER = os.environ.get('XMAGE_MASTER', pathlib.Path('/opt/git/github.com/magefree/mage/master'))
STAGE = os.environ.get('XMAGE_STAGE', pathlib.Path('/opt/git/github.com/fenhl/mage/stage'))

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

def iter_implemented(*, repo=MASTER):
    for set_class in (repo / 'Mage.Sets' / 'src' / 'mage' / 'sets').iterdir():
        if set_class.is_dir():
            continue
        set_code = None
        with set_class.open() as f:
            text = f.read()
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
    return '[{}](https://mtg.wtf/card/{}/{})'.format(name, url_set_code.lower(), number)

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
