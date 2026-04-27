# Use official Playwright image that has ALL deps pre-installed
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Expose port
EXPOSE 10000

# Start the app
CMD ["python", "server.py"]
