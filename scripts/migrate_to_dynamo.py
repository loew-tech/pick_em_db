import json
from datetime import datetime, timezone
from uuid import uuid4

import boto3

TABLE_NAME = "PickEmTable"
DATA_FILE = "../db.json"

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

with table.batch_writer() as batch:
    for category in data:
        category_name = category["name"]

        for choice in category["choices"]:
            item = {
                "user_id": "stevebot",
                "created_at": f"{datetime.now(timezone.utc).isoformat()}#{uuid4()}",
                "category_id": category_name,
                "name": choice["name"],
                "interest": choice["interest"],
                "effort": choice["effort"],
            }

            batch.put_item(Item=item)

            print(f"Inserted: {choice['name']}")

print("Table populated successfully.")