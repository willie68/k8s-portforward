# Logging System Documentation

## Overview

The Portforward application now includes a comprehensive **background logging system** that records all important events to log files. Logs are written asynchronously to avoid blocking the UI, and the log files are automatically rotated to manage disk space.

## Features

### Events Logged

1. **Port Forward Started**
   - Timestamp when a port-forward becomes RUNNING
   - Forward name, resource, port mapping, and namespace
   - Example: `2024-04-07 14:23:15 - INFO - Port-forward STARTED: krakend (deployment/krakend) 8443:8443 in namespace one-dm-dev`

2. **Port Forward Stopped**
   - Timestamp when a port-forward is stopped
   - Forward name
   - Example: `2024-04-07 14:25:30 - INFO - Port-forward STOPPED: krakend (User action)`

3. **Health Check Failures**
   - Timestamp of each health check failure
   - Forward name, port, endpoint path
   - Failure count (to help identify patterns)
   - Additional error details (HTTP status, connection errors, etc.)
   - Example: `2024-04-07 14:26:45 - WARNING - Health check FAILED for krakend: http://127.0.0.1:8443/health (failure #2) - HTTP 503`

4. **Port Forward Errors**
   - Startup errors, permission issues, kubectl not found, etc.
   - Example: `2024-04-07 14:27:00 - ERROR - Port-forward ERROR (krakend): kubectl not found – is it installed and in PATH?`

5. **Auto-Restart Events**
   - Logs when port-forwards are automatically restarted
   - Includes the reason (e.g., health check failures)
   - Example: `2024-04-07 14:28:15 - INFO - Port-forward RESTARTING: krakend (Health check failures (max 3 reached))`

## Configuration

Logging is configured in `config.yaml`:

```yaml
logging:
  enabled: true                    # Set to false to disable logging
  log_dir: "./logs"               # Directory where log files are stored
  log_file: "portforward.log"     # Filename for the log file
```

### Configuration Options

- **enabled**: Boolean (default: `true`)
  - Set to `false` to disable all logging
  - Can be useful for reducing file I/O on very busy systems

- **log_dir**: String (default: `./logs`)
  - Relative or absolute path where log files are stored
  - Directory is created automatically if it doesn't exist
  - Examples:
    - `./logs` - Relative to the application directory
    - `C:\Users\MyUser\Documents\portforward-logs` - Absolute Windows path
    - `~/portforward-logs` - Home directory (Unix-style)

- **log_file**: String (default: `portforward.log`)
  - Name of the log file
  - Recommended: Keep it simple, e.g., `portforward.log`, `k8s-forwards.log`

## Log File Management

### Rotation Policy

- **Max File Size**: 5 MB per log file
- **Backup Count**: Keeps 5 rotated backups
- **Total Storage**: Up to ~30 MB for all log files combined

When a log file reaches 5 MB:
1. Current file is renamed to `portforward.log.1`
2. Previous backups are rotated: `.1` → `.2`, `.2` → `.3`, etc.
3. `.6` and beyond are deleted
4. A new `portforward.log` is created for new entries

### Log File Format

```
2024-04-07 14:23:15 - INFO - Port-forward STARTED: krakend (deployment/krakend) 8443:8443 in namespace one-dm-dev
2024-04-07 14:24:00 - INFO - Port-forward STARTED: secretary (deployment/secretary) 8443:8443 in namespace one-dm-dev
2024-04-07 14:26:45 - WARNING - Health check FAILED for krakend: http://127.0.0.1:8443/health (failure #2) - HTTP 503
2024-04-07 14:28:15 - INFO - Port-forward RESTARTING: krakend (Health check failures (max 3 reached))
2024-04-07 14:28:18 - INFO - Port-forward STARTED: krakend (deployment/krakend) 8443:8443 in namespace one-dm-dev
2024-04-07 14:30:00 - INFO - Port-forward STOPPED: secretary (User action)
```

## Usage Examples

### How to Find Log Files

**Windows (Default)**
```
C:\Users\YourUsername\AppData\Roaming\portforward\logs\portforward.log
```

**Windows (Custom Directory)**
If you set `log_dir: C:\MyLogs`, logs will be at:
```
C:\MyLogs\portforward.log
```

**Linux/macOS (Relative Path)**
Logs will be in the application directory:
```
./logs/portforward.log
```

### Analyzing Logs

1. **Find when a specific forward stopped**
   ```
   grep "STOPPED: myservice" portforward.log
   ```

2. **Find all health check failures**
   ```
   grep "Health check FAILED" portforward.log
   ```

3. **Count errors for a specific service**
   ```
   grep "myservice" portforward.log | grep "ERROR"
   ```

4. **View recent activity (last 20 lines)**
   ```
   tail -20 portforward.log
   ```

5. **Find restarts due to health check failures**
   ```
   grep "RESTARTING.*Health check failures" portforward.log
   ```

## Performance Impact

- **Minimal**: Logging uses asynchronous file I/O and does not block the UI thread
- **Disk Space**: ~30 MB maximum with default rotation settings
- **Memory**: Negligible overhead (< 1 MB)

## Troubleshooting

### No log file created

1. Check that `logging.enabled: true` in your config.yaml
2. Verify the `log_dir` path is writable:
   - For relative paths, check the application directory permissions
   - For absolute paths, ensure the directory exists or can be created
3. Check application error messages in the UI or console

### Log file is very large

- This shouldn't happen with the 5 MB rotation limit
- If it does, check the `log_file` size in `log_dir`
- Consider reducing activity or disabling logging temporarily

### Cannot find log files

- Check the configured `log_dir` in config.yaml
- If using a relative path like `./logs`, logs are relative to:
  - The application start directory (if run from command line)
  - The application installation directory (if run as installed application)
- Look for hidden directories if using `~` (home directory)

## Implementation Details

### Architecture

- **LoggingManager**: Singleton instance that manages the logger
- **Process Manager Integration**: Automatically logs all relevant events
- **Thread Safety**: Uses locks to ensure thread-safe logging from multiple background threads
- **Graceful Shutdown**: Logs are flushed when the application closes

### Log Levels

- **INFO**: Normal operations (start, stop, restart)
- **WARNING**: Non-critical issues (health check failures)
- **ERROR**: Critical issues (startup failed, permission denied)

## Example Configuration Files

### Minimal Setup (Default Logs)
```yaml
forwards:
  - name: "My Service"
    resource: "deployment/myapp"
    local_port: 8080
    remote_port: 8080

# Uses default logging (logs to ./logs/portforward.log)
```

### Custom Log Location (Windows)
```yaml
logging:
  enabled: true
  log_dir: "C:\\Users\\MyUser\\Documents\\K8SLogs"
  log_file: "portforward-2024.log"

forwards:
  - name: "My Service"
    resource: "deployment/myapp"
    local_port: 8080
    remote_port: 8080
```

### Disable Logging (Development/Testing)
```yaml
logging:
  enabled: false

forwards:
  - name: "My Service"
    resource: "deployment/myapp"
    local_port: 8080
    remote_port: 8080
```

### Shared Drive Logging (Team Environments)
```yaml
logging:
  enabled: true
  log_dir: "\\\\ShareServer\\k8s-logs\\individual-logs"
  log_file: "portforward.log"

forwards:
  - name: "My Service"
    resource: "deployment/myapp"
    local_port: 8080
    remote_port: 8080
```
