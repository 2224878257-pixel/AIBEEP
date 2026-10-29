FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN mkdir -p /data
EXPOSE 8080
CMD ["python", "backend.py"]
