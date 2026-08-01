FROM python:3.12-slim
WORKDIR /app
COPY requirements-commercial.txt .
RUN pip install --no-cache-dir -r requirements-commercial.txt
COPY server ./server
RUN mkdir -p /app/data/uploads
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "server.helpcat.app:app", "--host", "0.0.0.0", "--port", "8000"]
