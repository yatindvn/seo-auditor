# WebSocket Documentation

## Connection Endpoint
- **URL**: `ws://localhost:5000`

## Events Broadcasted

### 1. `connect`
Triggered immediately upon client connection.
```json
{
  "event": "connect",
  "message": "Connected to SEO Auditor WebSocket Server"
}
```

### 2. `crawl:start`
Emitted when an audit starts.
```json
{
  "event": "crawl:start",
  "payload": {
    "url": "https://example.com",
    "timestamp": 1784748600000
  }
}
```

### 3. `crawl:complete`
Emitted upon audit completion.
```json
{
  "event": "crawl:complete",
  "payload": {
    "url": "https://example.com",
    "pages": 8
  }
}
```

### 4. `crawl:error`
Emitted if crawling encounters an unrecoverable failure.
```json
{
  "event": "crawl:error",
  "payload": {
    "url": "https://example.com",
    "error": "Connection timed out"
  }
}
```
