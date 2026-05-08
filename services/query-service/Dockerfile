FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off --upgrade pip "setuptools<81" wheel && pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off -r /app/requirements.txt

COPY . /app

EXPOSE 8006

<<<<<<< HEAD
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8006"]

=======
CMD ["sh", "-c", "python manage.py runserver 0.0.0.0:8006"]
>>>>>>> c791036 (final update)
