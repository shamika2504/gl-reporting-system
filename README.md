# GL Regulatory Reporting System

This repository contains the initial backend skeleton for a GL regulatory reporting system built with FastAPI, PostgreSQL, pgvector, Qdrant, Celery, Redis, AWS S3, and Anthropic Claude.

## Structure

- backend/ for the FastAPI application and worker services
- scripts/ for database initialization and data seeding
- docker-compose.yml for local development infrastructure

## Getting started

1. Copy .env.example to .env and adjust values.
2. Run docker-compose up.
3. Visit http://localhost:8000/health for the service health endpoint.
