FROM python:3.14-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 5000

# Run with Gunicorn (Production server)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]