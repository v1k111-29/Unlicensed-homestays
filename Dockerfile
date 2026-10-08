# NOT BUILT: Docker is not installed on the dev machine (Q14). Built and tested in M11.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
WORKDIR /app/src
# Needs DJANGO_SECRET_KEY, DATABASE_URL and DJANGO_ALLOWED_HOSTS at run time.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
