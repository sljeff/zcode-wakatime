# Hook payload samples (ZCode 0.17.0)

Real payloads captured from ZCode 0.17.0 on macOS, one file per event, with
identifiers redacted (`sess_redacted`, `turn_redacted`, `uuid_redacted`,
`call_redacted`, `/Users/you`).

The plugin consumes `hook_event_name`, `cwd`, `session_id`, `tool_name`,
`tool_input` (and, indirectly, the presence of `tool_response` /
`error` fields). Both snake_case and camelCase copies of several fields exist
in real payloads; the snake_case forms are the stable, Claude-compatible ones
and are what this plugin reads.

Note that `transcript_path` points to a temp file that ZCode deletes right
after the hook returns — it is not a durable transcript.
