# NOT BUILT: Docker is not installed on the dev machine. Entry point stubbed until M2.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
WORKDIR /app/src
# TODO(M2): CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
CMD ["python", "-c", "print('app entrypoint not implemented until M2')"]
