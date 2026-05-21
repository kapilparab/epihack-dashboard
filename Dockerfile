FROM public.ecr.aws/lambda/python:3.12

# Install dependencies into the Lambda task root
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ${LAMBDA_TASK_ROOT}/app/

# Lambda handler: module.attribute
CMD ["app.main.handler"]
