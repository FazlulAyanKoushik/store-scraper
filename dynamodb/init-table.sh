#!/bin/bash
# Optional: Pre-create the DynamoDB table on startup
# This is a fallback in case the backend's ensure_table() fails.

TABLE_NAME="store_scrape_results"

aws dynamodb create-table \
  --endpoint-url http://localhost:8000 \
  --region us-east-1 \
  --table-name $TABLE_NAME \
  --key-schema \
    AttributeName=store_name,KeyType=HASH \
    AttributeName=scraped_at,KeyType=RANGE \
  --attribute-definitions \
    AttributeName=store_name,AttributeType=S \
    AttributeName=scraped_at,AttributeType=S \
  --billing-mode PAY_PER_REQUEST

echo "Table '$TABLE_NAME' created (or already exists)."
