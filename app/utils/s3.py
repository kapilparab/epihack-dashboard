import boto3
from fastapi import UploadFile
from app.config import get_settings

settings = get_settings()
_s3 = boto3.client(
    "s3",
    region_name=settings.DYNAMO_REGION,
    aws_access_key_id=settings.DYNAMO_ACCESS_KEY_ID,
    aws_secret_access_key=settings.DYNAMO_SECRET_ACCESS_KEY,
)


async def upload_report_image(report_id: str, subtype: str, file: UploadFile) -> str:
    """
    Upload a single image to S3 and return its public URL.

    Key layout: report_images/{report_id}/{subtype}/{filename}
    """
    key = f"report_images/{report_id}/{subtype}/{file.filename}"
    content = await file.read()

    _s3.put_object(
        Bucket=settings.S3_IMAGES_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type or "image/jpeg",
    )

    return f"https://{settings.S3_IMAGES_BUCKET}.s3.amazonaws.com/{key}"
