import boto3
import os
import time
from datetime import datetime

DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8001")
TABLE_NAME = "store_scrape_results"


def get_client():
    return boto3.resource(
        "dynamodb",
        endpoint_url=DYNAMODB_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="fakekey",
        aws_secret_access_key="fakesecret",
    )


def ensure_table():
    client = get_client()
    try:
        table = client.Table(TABLE_NAME)
        table.load()
        print(f"Table '{TABLE_NAME}' already exists.")
    except client.meta.client.exceptions.ResourceNotFoundException:
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "store_name", "KeyType": "HASH"},
                {"AttributeName": "scraped_at", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "store_name", "AttributeType": "S"},
                {"AttributeName": "scraped_at", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"Table '{TABLE_NAME}' created.")


def save_result(store_name: str, product_count: int, products: list[str]):
    client = get_client()
    table = client.Table(TABLE_NAME)
    table.put_item(Item={
        "store_name": store_name,
        "scraped_at": datetime.utcnow().isoformat(),
        "product_count": product_count,
        "products": products,
    })


def get_history(store_name: str) -> list[dict]:
    client = get_client()
    table = client.Table(TABLE_NAME)
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("store_name").eq(store_name)
    )
    return response.get("Items", [])
