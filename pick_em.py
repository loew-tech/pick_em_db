from datetime import datetime, timezone
import json
from collections import namedtuple
from random import randint
from typing import List, Dict
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key, Attr
from cachetools import TTLCache, cached
from flask import Flask, request, make_response, jsonify, Response
from flask.typing import ResponseReturnValue
from flask_cors import CORS

from constants import *

cache = TTLCache(maxsize=100, ttl=60)

TABLE_NAME = "PickEmTable"
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

Option = namedtuple('Option', ['name', 'start', 'weight', 'category'])

app = Flask(__name__)
CORS(app)

# @TODO: pass user_id or get from session
with open('.env') as env_file:
    user_id = env_file.readline().strip()

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
    return _get_category(category)

@cached(cache)
def _get_category(category: str) -> Dict[str, str|List[Dict[str, str]]]:
    print('making dynamo call')
    response = table.query(
        IndexName="category",
        KeyConditionExpression=Key(CATEGORY_ID).eq(category),
        FilterExpression=Attr(USER_ID).eq(user_id),
        ProjectionExpression="#n, effort, interest",
        ExpressionAttributeNames={"#n": NAME}
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
        category: List[Dict[str, str]] = _get_category(c)[CHOICES]
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
    response = table.query(
        IndexName=CATEGORY,
        KeyConditionExpression=Key(CATEGORY_ID).eq(category),
        FilterExpression=Attr(USER_ID).eq(user_id) & Attr(NAME).eq(name),
    )

    item = response.get(ITEMS, [None])[0]
    if item is None:
        return {"msg": f"name {name} not found in {category}"}, 404
    i = request.json.get(INTEREST, item[INTEREST])
    e = request.json.get(EFFORT, item[EFFORT])
    update_expression = 'SET interest = :i, effort = :e'
    expression_values = {':i': i, ':e': e}

    table.update_item(
        Key={
            USER_ID: item[USER_ID],
            CREATED_AT: item[CREATED_AT],
        },
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
        ReturnValues="UPDATED_NEW",
    )
    return {'msg': f'successfully updated {name} in {category}'}, 202


@app.post('/categories/<string:category>/add/<string:name>')
def add_category(category, name: str) -> ResponseReturnValue:
    data = request.get_json(silent=True)
    if data is None:
        return {'msg': 'JSON body required'}, 400
    if not category or not name:
        return {'msg': '"category" and "name" must be provided'}, 400
    if INTEREST not in data or EFFORT not in data:
        return {'msg': 'fields "interest" and "effort" are required'}, 400

    name = name.replace('+', ' ')
    item = {
       USER_ID: user_id,
       CREATED_AT: f"{datetime.now(timezone.utc).isoformat()}#{uuid4()}",
       CATEGORY_ID: category,
       NAME: name,
       **data
    }
    table.put_item(Item=item)
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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
