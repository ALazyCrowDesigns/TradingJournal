# CSV Import Threading Fix Summary

## Problem
The CSV import function was failing with the Qt threading error:
```
QObject::setParent: Cannot set parent, new parent is in a different thread.
```

## Root Cause
The `WorkerRunnable` class was calling Qt UI callbacks directly from background threads, which violates Qt's thread safety requirements. In Qt, all UI operations must be performed on the main thread.

## Solution
Replaced the direct callback invocation with a proper Qt signal-slot mechanism:

1. **Created `WorkerSignaler` class**: A `QObject` subclass that can emit signals
2. **Modified `WorkerRunnable`**: Now uses signals to communicate with the main thread
3. **Thread-safe communication**: Qt signals are automatically queued when crossing thread boundaries

## Code Changes

### Before (Problematic):
```python
@Slot()
def run(self) -> None:
    try:
        result = self.fn(*self.args, **self.kwargs)
        if self.callback:
            self.callback(result)  # ❌ Direct call from background thread
    except Exception as e:
        if self.error_callback:
            self.error_callback(str(e))  # ❌ Direct call from background thread
```

### After (Thread-safe):
```python
class WorkerSignaler(QObject):
    """Helper class to emit signals from worker threads"""
    finished = Signal(object)
    failed = Signal(str)

class WorkerRunnable(QRunnable):
    def __init__(self, fn, callback=None, error_callback=None, *args, **kwargs):
        # ... initialization ...
        self.signaler = WorkerSignaler()
        if self.callback:
            self.signaler.finished.connect(self.callback)
        if self.error_callback:
            self.signaler.failed.connect(self.error_callback)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            if self.callback:
                self.signaler.finished.emit(result)  # ✅ Signal emission (thread-safe)
        except Exception as e:
            if self.error_callback:
                self.signaler.failed.emit(str(e))  # ✅ Signal emission (thread-safe)
```

## Impact
- ✅ CSV import now works without Qt threading errors
- ✅ All background operations (dry run, import, backfill) are thread-safe
- ✅ Proper separation between business logic (background) and UI updates (main thread)
- ✅ No performance impact - signals are efficient and Qt's standard mechanism

## Testing
- Created comprehensive test suite that verifies both success and error scenarios
- All tests pass, confirming the threading fix works correctly
- Application starts and initializes without errors

## Files Modified
- `src/journal/ui/main_window.py`: Fixed `WorkerRunnable` class and added `WorkerSignaler`

The CSV import functionality should now work reliably without any Qt threading issues.
