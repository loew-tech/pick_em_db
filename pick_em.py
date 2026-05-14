import json
from collections import namedtuple
from random import randint
from typing import List, Dict

import boto3
from boto3.dynamodb.conditions import Key, Attr
from flask import Flask, request, make_response, jsonify, Response
from flask.typing import ResponseReturnValue
from flask_cors import CORS

from constants import *

TABLE_NAME = "PickEmTable"
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

Option = namedtuple('Option', ['name', 'start', 'weight', 'category'])

app = Flask(__name__)
CORS(app)

# @TODO: pass user_id or get from session
with open('.env') as env_file:
    user_id = env_file.readline().strip()

with open('db.json') as in_:
    db = {e[NAME]: e[CHOICES] for e in json.load(in_)}


@app.get('/')
def index() -> ResponseReturnValue:
    return '<div>Hello World</div>'


@app.get('/categories')
def categories() -> ResponseReturnValue:
    response = table.query(
        KeyConditionExpression=Key(USER_ID).eq(user_id),
        ProjectionExpression = CATEGORY_ID
    )
    return sorted({item[CATEGORY_ID] for item in response.get(ITEMS, [])})


@app.get('/categories/<string:category>')
def get_category(category: str) -> ResponseReturnValue:
    response = table.query(
        IndexName="category",
        KeyConditionExpression=Key(CATEGORY_ID).eq(category),
        FilterExpression=Attr(USER_ID).eq(user_id),
        ProjectionExpression="#n, effort, interest",
        ExpressionAttributeNames={
            "#n": NAME  # 'name' can be safely aliased (defensive practice)
        }
    )
    return {NAME: category, CHOICES: response.get(ITEMS, [])}


@app.get('/categories/pick')
def pick() -> ResponseReturnValue:
    cats = request.args.getlist('categories')
    i = request.args.get('interest', 'low')
    e = request.args.get('effort', 'low')
    if not cats or i not in TIERS or e not in TIERS:
        return make_response(jsonify(error="Invalid  categories, interest or "
                                           "effort selection"), 400)

    if not (options := get_options(i, e, cats)):
        return {'selection': 'NO ITEMS FOUND MATCHING CRITERIA',
                'category': 'NOT FOUND'}
    selection = pick_item(options)
    app.logger.info(f'Picked {selection.name} from {selection.category}')
    return {'selection': selection.name, 'category': selection.category}


def get_options(interest, effort: str, cats: List[str]) -> List[Option]:
    i = {*TIERS[TIERS.index(interest):]}
    e = {*TIERS[:TIERS.index(effort) + 1]}
    options: List[Option] = []
    for c in cats:
        # @TODO: remove warnings
        category: List[Dict[str, str]] = get_category(c)[CHOICES]
        for d in category:
            if not (d[INTEREST] in i and d[EFFORT] in e):
                continue
            start = options[-1].start + options[-1].weight if options else 0
            # @TODO: is this how I want to handle interest < effort
            wght = max(1, WEIGHTS[d[INTEREST]] // WEIGHTS[d[EFFORT]])
            options.append(Option(name=d[NAME], start=start, weight=wght,
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
def remove(category, name: str) -> ResponseReturnValue:
    name = name.replace('+', ' ')
    response = table.query(
        IndexName=CATEGORY,
        KeyConditionExpression=Key(CATEGORY_ID).eq(category),
        FilterExpression=Attr(USER_ID).eq(user_id) & Attr(NAME).eq(name),
        ProjectionExpression="user_id, created_at"
    )
    items = response.get(ITEMS, [])
    if not items:
        return {'msg': f'name {name} not found in {category}'}, 404
    for item in items:
        table.delete_item(
            Key={USER_ID: item[USER_ID], CREATED_AT: item[CREATED_AT]}
        )
    return {'msg': f'successfully removed {name} from {category}'}


@app.put('/categories/<string:category>/edit/<string:name>')
def edit(category, name: str) -> ResponseReturnValue:
    name = name.replace('+', ' ')
    item = next(filter(lambda d: d[NAME] == name, db[category]), None)
    if item is None:
        return {"msg": f'name {name} not found in {category}'}, 404
    item[INTEREST] = request.json.get(INTEREST, item[INTEREST])
    item[EFFORT] = request.json.get(EFFORT, item[EFFORT])
    dump_db()
    return {'msg': f'successfully updated {name} in {category}'}, 202


@app.post('/categories/<string:category>/add/<string:name>')
def add_category(category, name: str) -> ResponseReturnValue:
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
def bulk_add_to_category() -> ResponseReturnValue:
    if type(request.json) is not list:
        return {'msg': 'list of "category" "option" pairs must be provided in '
                       'body'}, 400

    return {'msg': NotImplemented}, 404

    warnings = _bulk_add_options(request.json)
    if len(warnings) == len(request.json):
        return {'msg': 'failed to add any options', 'warnings': warnings}, 422
    if warnings:
        return {'msg': 'added some choices with failures',
                'warnings': warnings}, 207
    return {'msg': 'successfully added all options'}, 200


def _bulk_add_options(options: List[Dict]) -> List[str]:
    return NotImplemented


def dump_db():
    with open('db.json', 'w') as out:
        json.dump([{"name": name_, "choices": choices} for
                   name_, choices in db.items()], out,
                  indent=2)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
