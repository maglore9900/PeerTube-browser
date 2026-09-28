"""HTTP handlers for API endpoints.

Modules:
- similar: main Engine read handler for recommendations and read endpoints.
- video: fetches video metadata for /api/video and /api/video/refresh.
- internal_client_reads: internal read endpoints used by Client service.
- internal_events: bridge ingest endpoint for normalized Client events and hourly raw-event retention strip.
"""
