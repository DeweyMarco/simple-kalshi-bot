FROM mcr.microsoft.com/devcontainers/python:1-3.11

# Install system dependencies needed to build cryptography and other wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libssl-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Keep container lean; dependencies are installed in postCreateCommand
