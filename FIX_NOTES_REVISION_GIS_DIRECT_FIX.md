# Revision + GIS Direct Fix

This build fixes two blocking issues observed in the UI:

1. Revision submission could appear stuck.
   - Revision now works both when the LangGraph is paused at an interrupt and when it is not.
   - If no target dimension can be inferred, the backend returns `need_dimension` instead of pretending to revise.
   - Background task errors are sent to the frontend as SSE error messages.

2. GIS layout could fail with `_gis_error_handler() missing 1 required positional argument: 'error'`.
   - GIS error handler now supports both LangGraph calling conventions.
   - GIS generation is now isolated from the normal chat/revision graph path.
   - If the GIS ReAct pipeline fails, the backend still emits valid fallback map layers so the map tab can display a layout.

Notes:
- MAX_TOKENS remains large; this build does not reduce generation token budget.
- Keep `.env` local. Do not upload `.env` to GitHub.
