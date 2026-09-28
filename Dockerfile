FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABRIDGE_DATA_DIR=/data

# Microsoft ODBC driver for SQL Server is optional; uncomment if you need SQL Server via pyodbc.
# RUN apt-get update && apt-get install -y curl gnupg unixodbc && \
#     curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/ms.gpg && \
#     echo "deb [signed-by=/usr/share/keyrings/ms.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql.list && \
#     apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-drivers.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-drivers.txt

COPY databridge ./databridge
COPY samples ./samples

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "databridge.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
