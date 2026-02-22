FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt update && apt install -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen

COPY . .

CMD [ "bash" ]
