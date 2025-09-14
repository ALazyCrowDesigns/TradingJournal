# Trading Journal Startup Performance Analysis

## Executive Summary

The application currently takes **~1.24 seconds** to start up, with the main bottlenecks being:

1. **MainWindow creation (0.428s - 34.5%)** - Most expensive operation
2. **SQLAlchemy import (0.238s - 19.2%)** - Heavy library import
3. **Container import (0.214s - 17.2%)** - Dependency injection setup
4. **Config import (0.136s - 11.0%)** - Configuration loading
5. **Models import (0.074s - 6.0%)** - Database models

## Detailed Analysis

### 1. MainWindow Creation Issues (0.428s)

**Root Causes:**
- **Eager data loading**: The MainWindow immediately loads trades data during initialization
- **Analytics computation**: `refresh_analytics()` is called during init, triggering expensive database queries
- **Session restoration**: Attempts to restore previous session state, including loading trades
- **UI component initialization**: Creates all widgets, models, and connections upfront

**Evidence from logs:**
```
SELECT count(trades.id), sum(...), avg(...) FROM trades  # Analytics query
SELECT trades.id, trades.profile_id, ... FROM trades ORDER BY trades.trade_date DESC LIMIT 10000 OFFSET 0  # Data loading
```

### 2. Database-Related Bottlenecks

**Issues identified:**
- **Synchronous table creation**: `Base.metadata.create_all(engine)` runs during DAO import
- **Heavy SQL logging**: Development mode enables verbose SQL logging
- **Large data queries**: Loading 10,000 trades during startup
- **Multiple database connections**: Analytics and data loading happen separately

### 3. Import Performance Issues

**Heavy imports:**
- **SQLAlchemy (0.238s)**: Large ORM library with many submodules
- **PySide6 (0.067s)**: GUI framework import
- **Container dependencies**: Pulls in many service classes

## Optimization Recommendations

### Priority 1: Lazy Loading & Deferred Initialization

1. **Defer MainWindow data loading**
   ```python
   # Instead of loading data in __init__, use QTimer.singleShot
   QTimer.singleShot(0, self._delayed_init)
   
   def _delayed_init(self):
       self.restore_prefs()
       self.apply_column_visibility()
       self.refresh_analytics()  # Move this out of __init__
   ```

2. **Lazy analytics loading**
   ```python
   # Don't compute analytics until user clicks Analytics tab
   tab_widget.currentChanged.connect(self._on_tab_changed)
   
   def _on_tab_changed(self, index):
       if index == 1 and not self._analytics_loaded:  # Analytics tab
           self.refresh_analytics()
           self._analytics_loaded = True
   ```

3. **Reduce initial data load**
   ```python
   # Load smaller initial dataset (100 rows instead of 10,000)
   self.model = EditableTradesModel(page_size=100)  # Already implemented
   ```

### Priority 2: Database Optimization

1. **Disable SQL logging in production**
   ```python
   # In dao.py _mk_engine()
   echo=False,  # Always disable, or use settings.app_env == "debug"
   ```

2. **Optimize database queries**
   ```python
   # Use LIMIT for initial analytics
   def get_summary_light(self, filters=None, limit=1000):
       # Only analyze recent trades for startup
   ```

3. **Connection pooling optimization**
   ```python
   # In _mk_engine()
   pool_size=1,           # Single connection for SQLite
   max_overflow=0,        # No overflow connections
   pool_pre_ping=False,   # Skip ping for SQLite
   ```

### Priority 3: Import Optimization

1. **Lazy service imports**
   ```python
   # In container.py, use Factory instead of Singleton for heavy services
   analytics_service = providers.Factory(  # Was Singleton
       AnalyticsService,
       # ...
   )
   ```

2. **Conditional imports**
   ```python
   # Only import heavy modules when needed
   def get_analytics_service(self):
       if not hasattr(self, '_analytics_service'):
           from .services.analytics import AnalyticsService
           self._analytics_service = AnalyticsService(...)
       return self._analytics_service
   ```

### Priority 4: UI Optimization

1. **Progressive UI loading**
   ```python
   # Show window immediately, populate content progressively
   def __init__(self, container):
       super().__init__()
       self._setup_basic_ui()  # Minimal UI
       self.show()  # Show window early
       QTimer.singleShot(10, self._setup_advanced_ui)  # Heavy UI later
   ```

2. **Virtual scrolling optimization**
   ```python
   # Reduce initial cache size
   self._cache_size = 100  # Was 1000
   ```

## Implementation Plan

### Phase 1: Quick Wins (Target: 30% improvement)
- [ ] Disable SQL logging in production mode
- [ ] Defer analytics loading until tab is clicked
- [ ] Reduce initial data page size to 100 rows
- [ ] Move heavy UI initialization to QTimer.singleShot

### Phase 2: Architectural Changes (Target: 50% improvement)
- [ ] Implement lazy service loading in container
- [ ] Add progressive UI loading
- [ ] Optimize database connection settings
- [ ] Implement conditional session restoration

### Phase 3: Advanced Optimizations (Target: 70% improvement)
- [ ] Implement startup splash screen
- [ ] Add background data preloading
- [ ] Cache frequently used data
- [ ] Optimize import structure

## Expected Results

With these optimizations, startup time should reduce from **1.24s** to:
- **Phase 1**: ~0.87s (30% improvement)
- **Phase 2**: ~0.62s (50% improvement) 
- **Phase 3**: ~0.37s (70% improvement)

## Monitoring

Add startup timing to track improvements:
```python
# In app.py
import time
start_time = time.time()
# ... initialization code ...
print(f"Startup completed in {time.time() - start_time:.3f}s")
```

## Risk Assessment

**Low Risk:**
- SQL logging disable
- Deferred analytics loading
- Reduced page sizes

**Medium Risk:**
- Lazy service loading (may break dependency injection)
- Progressive UI loading (may cause UI flicker)

**High Risk:**
- Major architectural changes to container
- Conditional session restoration (may lose data)

## Conclusion

The current 1.24s startup time is primarily caused by eager data loading and heavy database queries during MainWindow initialization. The biggest impact will come from deferring expensive operations until they're actually needed, particularly analytics computation and large data queries.
