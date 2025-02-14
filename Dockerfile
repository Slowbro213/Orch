# Use an official Python runtime as the base image
FROM python:3.11-slim

# Install Docker CLI and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo \
    "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
    \"$(. /etc/os-release && echo \"$VERSION_CODENAME\")\" stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# Set working directory to /app
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

ENV PORT=5000
# Expose the Flask port (default is 5000)
EXPOSE ${PORT:-5000}

# Set environment variables
ENV FLASK_APP=app.py
ENV DOCKER_HOST=unix:///var/run/docker.sock
ENV HOST_TMP_DIR=/tmp/
RUN mkdir -p $HOST_TMP_DIR && chmod 777 $HOST_TMP_DIR

# Change to the src/ directory and run Gunicorn with dynamic port
CMD ["sh", "-c", "cd src && gunicorn -k gevent -w 2 --threads 4 -b 0.0.0.0:$PORT test:app"]
