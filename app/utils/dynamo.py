from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Attr
from app.config import get_settings


def _serialize(obj):
    """Recursively prepare a Python object for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    return obj


def _deserialize(obj):
    """Recursively convert DynamoDB-returned types back to Python types."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _deserialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deserialize(i) for i in obj]
    return obj


class DynamoDBClient:
    """Single boto3 resource shared across all tables. Pass table_name per call."""

    def __init__(self):
        settings = get_settings()
        self._resource = boto3.resource(
            "dynamodb",
            region_name=settings.DYNAMO_REGION,
            aws_access_key_id=settings.DYNAMO_ACCESS_KEY_ID,
            aws_secret_access_key=settings.DYNAMO_SECRET_ACCESS_KEY,
        )
        self._tables: dict[str, object] = {}

    def _table(self, table_name: str):
        if table_name not in self._tables:
            self._tables[table_name] = self._resource.Table(table_name)
        return self._tables[table_name]

    def put_item(self, table_name: str, item: dict) -> None:
        self._table(table_name).put_item(Item=_serialize(item))

    def get_item(self, table_name: str, key: dict) -> dict | None:
        response = self._table(table_name).get_item(Key=key)
        item = response.get("Item")
        return _deserialize(item) if item else None

    def scan(self, table_name: str, filters: dict | None = None) -> list[dict]:
        """Full table scan with optional equality filters."""
        if not filters:
            response = self._table(table_name).scan()
        else:
            expr = None
            for k, v in filters.items():
                cond = Attr(k).eq(v)
                expr = cond if expr is None else expr & cond
            response = self._table(table_name).scan(FilterExpression=expr)
        return [_deserialize(item) for item in response.get("Items", [])]


# Single shared instance — import this everywhere
client = DynamoDBClient()
