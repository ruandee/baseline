import hashlib

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from patient_memory.config import Settings


class ObjectStore:
    def __init__(self, cfg: Settings):
        self.bucket = cfg.object_bucket
        self.client = boto3.client(
            "s3", endpoint_url=cfg.object_endpoint, aws_access_key_id=cfg.object_access_key,
            aws_secret_access_key=cfg.object_secret_key, region_name="us-east-1",
            config=Config(signature_version="s3v4", connect_timeout=3, read_timeout=5,
                          retries={"max_attempts": 1}, s3={"addressing_style": "path"}),
        )

    def initialize(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, content: bytes):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content,
                               ContentType="application/json", IfNoneMatch="*")

    def get(self, key: str, expected_hash: str):
        data = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError("source_hash_mismatch")
        return data

    def delete(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=key)
