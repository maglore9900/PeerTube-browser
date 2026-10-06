"""HTTP handlers for API endpoints.

Modules:
- similar: main Engine read handler for recommendations and read endpoints.
- video: fetches video metadata for /api/video and /api/video/refresh.
- internal_client_reads: internal read endpoints used by Client service, including the exact-key channel lookup behind a follow named by its channel.
- internal_events: bridge ingest endpoint for normalized Client events and hourly raw-event retention strip.
- internal_translate: bridge read of a video's English translate state and whether the translate worker is serving; cues from a stored job, or fetched within bounds from its own instance and cached in subtitles.db; bridge request that queues a whisper job for the video while the worker is serving.
"""
