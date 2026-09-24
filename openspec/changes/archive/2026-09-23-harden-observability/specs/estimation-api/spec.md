## ADDED Requirements

### Requirement: Unexpected errors
The system SHALL answer any unexpected server error, raised before the response has started, with `500` and the JSON body `{"error": {"code": "internal_error", "message": "Internal server error."}, "request_id": <string>}`, carrying the request id in the `X-Request-ID` header. It SHALL log one record with the request id, the exception type, and the stack locations (file, line, and function of each frame), and SHALL NOT include the exception message in the response or the log record, because messages can echo request data.

#### Scenario: Unexpected error answered and logged
- **WHEN** a handler raises an unexpected exception whose message contains request data
- **THEN** the response status is `500` with error code `internal_error` and the request id
- **AND** the log record contains the exception type and the raising function's stack location
- **AND** neither the response nor the log record contains the exception message
