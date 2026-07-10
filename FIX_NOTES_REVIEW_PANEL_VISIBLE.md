# Review Panel Visibility Fix

This package fixes the issue where, after Layer 2 or another layer finishes, the review/revision panel may disappear even though step mode is enabled and the next layer has not started.

## Key fixes

1. Frontend store now infers an awaiting-review layer when:
   - step mode is enabled;
   - a layer is fully completed;
   - the next layer has not started;
   - no dimensions are currently executing.

2. ReportViewer now has a stronger fallback to display the review/revision card even if the backend `layer_paused` SSE event is missed or the state is restored from history.

3. This keeps the buttons visible:
   - `批准并进入下一阶段`
   - `提交修订`

## Notes

- The package intentionally does not include `.env` or `frontend/.env.local` to avoid overwriting local API keys or leaking secrets.
- Copy the contents of this folder into your main project directory and replace existing files.
- Keep your existing `.venv` and `frontend/node_modules` folders.
