import json
from collections import namedtuple
from random import randint
from typing import List, Dict, Tuple, Union

from flask import Flask, request, make_response, jsonify, Response
from flask_cors import CORS

Option = namedtuple('Option', ['name', 'start', 'weight', 'category'])

app = Flask(__name__)
CORS(app)

tiers = ['low', 'medium', 'high']
weights = dict(zip(tiers, [1, 3, 12]))

NAME = "name"
INTEREST = 'interest'
EFFORT = 'effort'

CATEGORY = 'category'
CATEGORIES = 'categories'
OPTION = 'option'

with open('db.json') as in_:
    db = {e[NAME]: e['choices'] for e in json.load(in_)}


@app.get('/')
def index():
    return '<div>Hello World</div>'


@app.get('/categories')
def categories() -> List[str]:
    return [*db.keys()]


@app.get('/categories/<string:category>')
def get_category(category: str) -> Dict[str, str | Dict[str, str]]:
    if category not in db:
        return {'name': category, 'choices': []}
    return {'name': category, 'choices': db[category]}


@app.get('/categories/pick')
def pick() -> Union[Dict[str, str], Response]:
    cats = request.args.getlist('categories')
    i = request.args.get('interest', 'low')
    e = request.args.get('effort', 'low')
    if not cats or i not in tiers or e not in tiers:
        return make_response(jsonify(error="Invalid  categories, interest or "
                                           "effort selection"), 400)

    if not (options := get_options(i, e, cats)):
        return {'selection': 'NO ITEMS FOUND MATCHING CRITERIA',
                'category': 'NOT FOUND'}
    selection = pick_item(options)
    app.logger.info(f'Picked {selection.name} from {selection.category}')
    return {'selection': selection.name, 'category': selection.category}


def get_options(interest, effort: str, cats: List[str]) -> List[Option]:
    i = {*tiers[tiers.index(interest):]}
    e = {*tiers[:tiers.index(effort) + 1]}
    options: List[Option] = []
    for c in cats:
        for d in db.get(c, []):
            if not (d['interest'] in i and d['effort'] in e):
                continue
            start = options[-1].start + options[-1].weight if options else 0
            # @TODO: is this how I want to handle interest < effort
            wght = max(1, weights[d['interest']] // weights[d['effort']])
            options.append(Option(name=d['name'], start=start, weight=wght,
                                  category=c))
    return options


def pick_item(options: List[Option]) -> Option:
    start, stop = 0, len(options) - 1
    selection = randint(start, options[-1].start + options[-1].weight - 1)
    while start <= stop:
        mid = (start + stop) // 2
        end = options[mid].start + options[mid].weight
        if options[mid].start <= selection < end:
            return options[mid]
        elif end <= selection:
            start = mid + 1
        else:
            stop = mid - 1
    return Option(name='NOT FOUND', start=-1, weight=-1, category='NOT FOUND')


@app.delete('/categories/<string:category>/remove/<string:name>')
def remove(category, name: str) -> tuple[dict, int] | dict[str, str]:
    name = name.replace('+', ' ')
    indices = {d['name']: i for i, d in enumerate(db.get(category, []))}
    if name not in indices:
        return db, 404
    del db[category][indices[name]]
    if not db[category]:
        del db[category]
    dump_db()
    return {'msg': f'successfully removed {name} from {category}'}


@app.put('/categories/<string:category>/edit/<string:name>')
def edit(category, name: str) -> tuple[dict[str, str], int]:
    name = name.replace('+', ' ')
    item = next(filter(lambda d: d[NAME] == name, db[category]), None)
    if item is None:
        return {"msg": f'name {name} not found in {category}'}, 404
    item[INTEREST] = request.json.get(INTEREST, item[INTEREST])
    item[EFFORT] = request.json.get(EFFORT, item[EFFORT])
    dump_db()
    return {'msg': f'successfully updated {name} in {category}'}, 202


@app.post('/categories/<string:category>/add/<string:name>')
def add_category(category, name: str) -> tuple[dict[str, str], int]:
    if not category or not name:
        return {'msg': '"category" and "name" must be provided'}, 400
    if INTEREST not in request.json or EFFORT not in request.json:
        return {'msg': 'fields "interest" and "effort" are required'}, 400
    name = name.replace('+', ' ')
    item = {NAME: name, **request.json}
    choices = db.get(category, [])
    choices.append(item)
    db[category] = choices
    dump_db()
    return {'msg': f'successfully added {name} to {category}'}, 202


# @TODO: change "bulk_add" to "add" once old func is deprecated
@app.post('/categories/bulk_add')
def bulk_add_to_category() -> Tuple[dict[str, str], int]:
    if type(request.json) is not list:
        return {'msg': 'list of "category" "option" pairs must be provided in '
                       'body'}, 400

    warnings = _bulk_add_options(request.json)

    if len(warnings) == len(request.json):
        return {'msg': 'failed to add any options', 'warnings': warnings}, 422
    if warnings:
        return {'msg': 'added some choices with failures',
                'warnings': warnings}, 207
    return {'msg': 'successfully added all options'}, 200


def _bulk_add_options(options: List[Dict]) -> List[str]:
    warnings = []
    for obj in options:
        if (cat := obj.get(CATEGORY)) is None or (option := obj.get(OPTION)) \
                is None:
            warnings.append(f'failed to add {obj}. Missing category or '
                            f'option')
            continue
        if NAME not in option or INTEREST not in option or EFFORT not in \
                option:
            warnings.append('failed to add to category {cat} Invalid option. '
                            'Missing name, interest, or effort')
            continue

        if cat not in db:
            db[cat] = [option]
            continue

        if (existing_option := [i for i, opt in enumerate(db[cat]) if
                                opt[NAME] == option[NAME]]):
            db[cat][existing_option.pop()] = option
            continue

        db[cat].append(option)
    dump_db()
    return warnings


def dump_db():
    with open('db.json', 'w') as out:
        json.dump([{"name": name_, "choices": choices} for
                   name_, choices in db.items()], out,
                  indent=2)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
