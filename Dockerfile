FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (separate layer — cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser + all required system libraries
RUN playwright install chromium --with-deps

# Copy the rest of the application
COPY . .

EXPOSE 8000

CMD ["python", "main.py"]
